import webapp2
import webapp2_extras.routes
import webapp2_extras.security
import jinja2
from google.appengine.api import urlfetch
from google.appengine.api import taskqueue
from google.appengine.ext import db
from google.appengine.ext.db import polymodel
from datetime import datetime
from inspect import isfunction
import os
import json
import cStringIO
import csv
import mimeparse
import copy
import dateutil.parser
import dateutil.relativedelta
import logging
import urllib
import lxml.html
import appendr_cfg

################################################################################
# Config parameters and constants
################################################################################

# Is debugging enabled?
DEBUG = True

if DEBUG:
  logging.getLogger().setLevel(logging.DEBUG)

# How long should user agents cache OAuth access control OPTIONS, in seconds
OAUTH_ACCESS_CONTROL_MAX_AGE = 60*60*24*30 # 30 days

# How many task queues exist for queuing append tasks
NUMBER_OF_APPEND_TASK_QUEUES = 10
APPEND_TASK_QUEUES_PREFIX = 'queue'

# Jinja environment global variable
JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__) + '/web'),
    extensions=['jinja2.ext.autoescape'])

# MIME type
MIME_TYPE_JSON = 'application/json'
MIME_TYPE_FORM = 'application/x-www-form-urlencoded'
MIME_TYPE_TEXT = 'text/plain'
MIME_TYPE_HTML = 'text/html'
MIME_TYPE_CSV = 'text/csv'

# HTML Template names
TEMPLATE_BASE = 'base.html'
TEMPLATE_INDEX = 'index.html'
TEMPLATE_BINS = 'bins.html'
TEMPLATE_BIN = 'bin.html'
TEMPLATE_TASKS = 'tasks.html'
TEMPLATE_TASK = 'task.html'
TEMPLATE_OAUTH_TOKEN = 'oauth_token.html'

# CSV and JSON serialization params
CSV_DELIMITER = ';'
CSV_QUOTECHAR = '"'
JSON_INDENT = 2

# urlfetch params
URLFETCH_DEADLINE = 10
URLFETCH_VALIDATE_CERTS = True

# Length of Bin and Task ids
BIN_NAME_LENGTH = 20
TASK_NAME_LENGTH = 20

# Storage backends
STORAGE_BACKEND_GIST = 'gist'
STORAGE_BACKEND_DROPBOX = 'dropbox'
SUPPORTED_STORAGE_BACKENDS = {
    STORAGE_BACKEND_GIST : 0,
    STORAGE_BACKEND_DROPBOX : 1
}
DEFAULT_STORAGE_BACKEND = STORAGE_BACKEND_GIST

# Default format for serializing date and time
DEFAULT_DATETIME_FORMAT = '%Y-%m-%dT%H:%M:%SZ'

# Supported output formats for external service and default values
# (because gists don't support empty files)
SUPPORTED_OUTPUT_EXTERNAL_DATA_MIME_TYPES = [MIME_TYPE_JSON, MIME_TYPE_CSV]
DEFAULT_OUTPUT_EXTERNAL_DATA_MIME_TYPE = MIME_TYPE_JSON
OUTPUT_FORMATS_EMPTY_DATA = {
    MIME_TYPE_JSON : '[]\n',
    MIME_TYPE_CSV : 'date_created\n'
}

# Supported output formats for appendr application
SUPPORTED_OUTPUT_APPENDR_MIME_TYPES = [MIME_TYPE_HTML,
                                       MIME_TYPE_TEXT,
                                       MIME_TYPE_JSON]
DEFAULT_OUTPUT_APPENDR_MIME_TYPE = MIME_TYPE_JSON

# Supported input mime types
SUPPORTED_INPUT_PARAMS_MIME_TYPES = [MIME_TYPE_FORM, MIME_TYPE_JSON]
SUPPORTED_APPEND_DATA_MIME_TYPES = [MIME_TYPE_FORM, MIME_TYPE_JSON]

# Default filename into which data will be stored
DEFAULT_FILENAME = 'data.%s'

# Default message that will be set in the Gist description if the backend
# is Gist
DEFAULT_GIST_MESSAGE = ('Gist created automatically by appendr.appspot.com. '
                       'Data filename is: %s')

# Secret OAuth app info for external services
OAUTH_GITHUB_CLIENT_ID = appendr_cfg.github_client_id
OAUTH_GITHUB_CLIENT_SECRET = appendr_cfg.github_client_secret
OAUTH_DROPBOX_CLIENT_ID = appendr_cfg.dropbox_client_id
OAUTH_DROPBOX_CLIENT_SECRET = appendr_cfg.dropbox_client_secret

# Route names
ROUTE_NAME_INDEX = 'main'
ROUTE_NAME_BIN = 'bin'
ROUTE_NAME_BINS = 'bins'
ROUTE_NAME_TASKS = 'tasks'
ROUTE_NAME_TASK_STATUS = 'task_status'
ROUTE_NAME_TASK_APPEND = 'task_append'
ROUTE_NAME_TASK_BIN_CLEANUP = 'task_bin_cleanup'
ROUTE_NAME_TASK_STATUS_CLEANUP = 'task_status_cleanup'
ROUTE_NAME_OAUTH_GITHUB = 'oauth_github'
ROUTE_NAME_OAUTH_DROPBOX = 'oauth_dropbox'

# How long must tasks and bins be unused before they can be removed, in hours
TASK_CLEANUP_MAX_AGE = 24
BIN_CLEANUP_MAX_AGE = 24*40

# How long for will a task be retried before giving up
TASK_RETRY_HOURS = 24*2

# Task status messages
TASK_STATUS_QUEUED = 'queued'
TASK_STATUS_COMPLETED = 'completed'
TASK_STATUS_RETRYING = 'retrying'
TASK_STATUS_FAILED = 'failed'

# Error messages
ERROR_MSG_NON_EMPTY_STRING_PARAM = ('Invalid value for parameter %s: %s. '
                                    'Parameter must be a non-empty string.')
ERROR_MSG_ELEMENT_OF_SET = ('Invalid value for parameter %s: %s. '
                            'Parameter must be one of: %s.')
ERROR_MSG_DEFINED = 'Parameter %s must be defined.'

################################################################################
# Helper functions
################################################################################

# Gets the best mime type match for the accept header,
# or uses a default mime type
def get_best_mime_match_or_default(accept_header, allowed_types, default=None):
    if accept_header is None:
        return default
    else:
        return mimeparse.best_match(allowed_types, accept_header)

# Input params validation helpers
def validate_non_empty_string(name, value):
    if not (isinstance(value, basestring) and value != ''):
        raise ValueError(ERROR_MSG_NON_EMPTY_STRING_PARAM % (name, value))

def validate_element_of_list(name, value, allowed_values):
    if value not in allowed_values:
        raise ValueError(ERROR_MSG_ELEMENT_OF_SET %
                         (name, value, allowed_values))

def validate_input_param(params, name, must_exist, validation_object, default):
    if must_exist and name not in params:
        raise ValueError(ERROR_MSG_DEFINED % (name,))

    if (name in params) and (params[name] != ''):
        if isfunction(validation_object):
            validation_object(name, params[name])
        elif isinstance(validation_object, list):
            validate_element_of_list(name, params[name], validation_object)
    else:
        params[name] = default

    return params

# Get a dictionary of params passed in the HTTP request
def get_request_params(req, content_type):
    if content_type == MIME_TYPE_FORM:
        return dict(req.params.copy())
    elif content_type == MIME_TYPE_JSON:
        return json.loads(req.body)
    else:
        # will never happen since we catch this before
        raise AppendrError(400, 'Invalid content type.')

# Get the name of the task queue which has append tasks for a specific bin
def get_queue_name_for_bin(bin_name):
    queue_num = sum([ord(ch) for ch in bin_name]) % NUMBER_OF_APPEND_TASK_QUEUES
    return APPEND_TASK_QUEUES_PREFIX + str(queue_num)

# Gets the sorted keys of a dictionary, with the creation date key in 1st place
def get_data_csv_key_list(params):
    keys = params.keys()
    keys.remove('date_created')
    keys.sort()
    keys.insert(0, 'date_created')
    return keys

# Gets a list of dict values sorted by the order of keys in another list
def get_dict_values_sorted(params, keys):
    return [params[key] for key in keys]

# Appends a dict of key-value data to an existing CSV document
def append_data_csv(old_content, params):
    key_list = get_data_csv_key_list(params)

    output = cStringIO.StringIO()
    csv_writer = csv.writer(
        output,
        delimiter=CSV_DELIMITER,
        quotechar=CSV_QUOTECHAR,
        quoting=csv.QUOTE_MINIMAL)

    if old_content == OUTPUT_FORMATS_EMPTY_DATA[MIME_TYPE_CSV]:
        csv_writer.writerow(key_list)

    data = get_dict_values_sorted(params, key_list)
    csv_writer.writerow(data)

    if old_content == OUTPUT_FORMATS_EMPTY_DATA[MIME_TYPE_CSV]:
        return output.getvalue()
    else:
        return old_content+output.getvalue()

# Appends a dict of key-value data to an existing JSON document
def append_data_json(old_content, params):
    json_data = json.loads(old_content)
    json_data.append(params)
    return json.dumps(json_data, indent=JSON_INDENT)

# Appends a dict of key-value data to an existing document
def append_data(old_content, output_format, params):
    params['date_created'] = \
        params['date_created'].strftime(DEFAULT_DATETIME_FORMAT)

    if output_format == MIME_TYPE_CSV:
        return append_data_csv(old_content, params)

    elif output_format == MIME_TYPE_JSON:
        return append_data_json(old_content, params)

    else:
        # will never happen since we catch this before
        raise AppendrError(400, 'Invalid output format.')

# Response for HTTP OPTIONS request which basically just sends OAuth headers
def setHTTPOptionsResponse(response,
                           oauth_origin='*',
                           oauth_methods=['GET'],
                           oauth_headers=['Content-Type']):
    headers = response.headers
    headers.add_header('Access-Control-Allow-Origin', oauth_origin)
    headers.add_header('Access-Control-Allow-Methods', ', '.join(oauth_methods))
    headers.add_header('Access-Control-Allow-Headers', ', '.join(oauth_headers))
    headers.add_header('Access-Control-Max-Age', OAUTH_ACCESS_CONTROL_MAX_AGE)
    headers.add_header('Allow', ', '.join(['OPTIONS'] + oauth_methods))
    response.set_status(200)

# Custom error class. Temporary here until I figure out how to use GAE http
# exceptions and error handling
class AppendrError(Exception):
    def __init__(self, code, msg):
        Exception.__init__(self, msg)
        self.code = code
        self.msg = msg

################################################################################
# Base Bin model
################################################################################

class Bin(polymodel.PolyModel):
    date_created = db.DateTimeProperty(auto_now_add=True)
    date_updated = db.DateTimeProperty(auto_now_add=True)
    output_format = db.StringProperty()
    storage_backend = db.StringProperty()
    storage_user_id = db.IntegerProperty()

    def get_url(self):
        return webapp2.uri_for(ROUTE_NAME_BIN,
                               bin_name=self.key().name(),
                               _full=True)

    def get_tasks_url(self):
        return webapp2.uri_for(ROUTE_NAME_TASKS,
                               bin_name=self.key().name(),
                               _full=True)

    def get_raw_content_url(self):
        return None

    def get_html_content_url(self):
        return None

    def get_info(self):
        bin_tasks = Task.all().filter('bin =', self.key())
        bin_tasks = bin_tasks.order('-date_created').fetch(None)

        return {
          'bin_id' : self.key().name(),
          'bin_url' : self.get_url(),
          'date_created' : self.date_created.strftime(DEFAULT_DATETIME_FORMAT),
          'date_updated' : self.date_updated.strftime(DEFAULT_DATETIME_FORMAT),
          'output_format' : self.output_format,
          'datetime_format' : DEFAULT_DATETIME_FORMAT,
          'storage_backend' : self.storage_backend,
          'content_raw_url' : self.get_raw_content_url(),
          'content_html_url' : self.get_html_content_url(),
          'tasks_url' : self.get_tasks_url(),
          'tasks' : [task.get_info() for task in bin_tasks]
        }

    @classmethod
    def generate_name(cls):
        bin_name = None
        while True:
            bin_name = \
                webapp2_extras.security.generate_random_string(BIN_NAME_LENGTH)

            bin = Bin.get_by_key_name(bin_name)
            if bin is None:
                  break

        return bin_name

    @classmethod
    def serialize(cls, bins, content_type):
        bins_info = None

        if isinstance(bins, Bin):
            bins_info = bins.get_info()
        else:
            bins_info = []
            for bin in bins:
                bins_info.append(bin.get_info())

        if content_type in [MIME_TYPE_JSON, MIME_TYPE_TEXT]:
            return json.dumps(bins_info, indent=JSON_INDENT)
        elif content_type in [MIME_TYPE_HTML]:
            if isinstance(bins, Bin):
                template = JINJA_ENVIRONMENT.get_template(TEMPLATE_BIN)
            else:
                template = JINJA_ENVIRONMENT.get_template(TEMPLATE_BINS)
            return template.render({'bins' : bins_info})

    @classmethod
    def get_user_id_for_token(cls, storage_backend, api_token):
        if storage_backend == STORAGE_BACKEND_GIST:
            return GistBin.get_user_id_for_token(api_token)
        elif storage_backend == STORAGE_BACKEND_DROPBOX:
            return DropboxBin.get_user_id_for_token(api_token)

    @classmethod
    def create(cls, params):
        validate_input_param(params, 'storage_backend', False,
                             SUPPORTED_STORAGE_BACKENDS.keys(),
                             DEFAULT_STORAGE_BACKEND)

        validate_input_param(params, 'output_format', False,
                             SUPPORTED_OUTPUT_EXTERNAL_DATA_MIME_TYPES,
                             DEFAULT_OUTPUT_EXTERNAL_DATA_MIME_TYPE)

        bin_name = Bin.generate_name()
        bin = None

        if params['storage_backend'] == STORAGE_BACKEND_GIST:
            bin = GistBin(key_name=bin_name)
        elif params['storage_backend'] == STORAGE_BACKEND_DROPBOX:
            bin = DropboxBin(key_name=bin_name)

        bin.output_format = params['output_format']
        bin.storage_backend = params['storage_backend']
        bin.initialize(bin_name, params)

        return bin

################################################################################
# GistBin model
################################################################################

class GistBin(Bin):
    is_public = db.BooleanProperty()
    gist_id = db.StringProperty()
    api_token = db.StringProperty()
    filename = db.StringProperty()

    def get_gist_html_url(self):
        return 'https://gist.github.com/' + self.gist_id

    def get_gist_api_url(self):
        return 'https://api.github.com/gists/' + self.gist_id

    def get_gist_raw_url(self):
        return 'https://gist.github.com/raw/' + self.gist_id + \
                '/' + self.filename

    def get_raw_content_url(self):
        return self.get_gist_raw_url()

    def get_html_content_url(self):
        return self.get_gist_html_url()

    def get_info(self):
        bin_info = Bin.get_info(self)

        bin_info['is_public'] = self.is_public
        bin_info['gist_id'] = self.gist_id
        bin_info['filename'] = self.filename
        bin_info['gist_api_url'] = self.get_gist_api_url()

        return bin_info

    @classmethod
    def get_user_id_for_token(cls, api_token):
        auth_headers = {
            'Authorization': 'token ' + api_token
        }

        response = urlfetch.fetch(
                            url='https://api.github.com/user',
                            headers=auth_headers,
                            deadline=URLFETCH_DEADLINE,
                            validate_certificate=URLFETCH_VALIDATE_CERTS)

        if response.status_code != 200:
            raise AppendrError(response.status_code, response.content)
        else:
            return json.loads(response.content)['id']

    def append_data(self, params):
        auth_headers = {
            'Authorization': 'token ' + self.api_token
        }

        gist_response = urlfetch.fetch(
                            url=self.get_gist_api_url(),
                            headers=auth_headers,
                            deadline=URLFETCH_DEADLINE,
                            validate_certificate=URLFETCH_VALIDATE_CERTS)

        if gist_response.status_code != 200:
            raise AppendrError(gist_response.status_code, '')

        json_gist = json.loads(gist_response.content)

        new_content = append_data(json_gist['files'][self.filename]['content'],
                                  self.output_format,
                                  params)

        new_payload = json.dumps({
            'files' : {
                self.filename : {
                    'content' : new_content
                }
            }
        })

        gist_headers = {
            'Content-Type': MIME_TYPE_JSON,
            'Authorization': 'token ' + self.api_token
        }

        result = urlfetch.fetch(url=self.get_gist_api_url(),
                                payload=new_payload,
                                method=urlfetch.POST,
                                headers=gist_headers,
                                deadline=URLFETCH_DEADLINE,
                                validate_certificate=URLFETCH_VALIDATE_CERTS)

        if result.status_code != 200:
            raise AppendrError(result.status_code, result.content)

    def initialize(self, bin_name, params):
        if 'is_public' in params:
            if params['is_public'] == 'true':
                params['is_public'] = True
            elif params['is_public'] == 'false':
                params['is_public'] = False

        validate_input_param(params, 'is_public', False,
                             [True, False],
                             False)

        validate_input_param(params, 'api_token', True,
                             validate_non_empty_string,
                             False)

        validate_input_param(params, 'filename', False,
                             validate_non_empty_string,
                             DEFAULT_FILENAME % \
                                 (params['output_format'].split('/')[-1],))

        gist_url = 'https://api.github.com/gists'

        gist_headers = {
            'Content-Type': MIME_TYPE_JSON,
            'Authorization': 'token ' + params['api_token']
        }

        empty_data_string = OUTPUT_FORMATS_EMPTY_DATA[params['output_format']]

        gist_payload = json.dumps({
            'description' : DEFAULT_GIST_MESSAGE % (params['filename'],),
            'public' : params['is_public'],
            'files' : {
                params['filename'] : {
                    'content' : empty_data_string
                }
            }
        })

        result = urlfetch.fetch(url=gist_url,
                                payload=gist_payload,
                                method=urlfetch.POST,
                                headers=gist_headers,
                                deadline=URLFETCH_DEADLINE,
                                validate_certificate=URLFETCH_VALIDATE_CERTS)

        if result.status_code != 201:
            raise AppendrError(result.status_code, '')

        json_content = json.loads(result.content)

        self.is_public = params['is_public']
        self.gist_id = json_content['id']
        self.api_token = params['api_token']
        self.filename = params['filename']
        self.storage_user_id = json_content['user']['id']

################################################################################
# DropboxBin model
################################################################################

class DropboxBin(Bin):
    api_token = db.StringProperty()
    filename = db.StringProperty()
    share_url = db.StringProperty()
    raw_url = db.StringProperty()

    def get_dropbox_api_url(self):
        return 'https://api-content.dropbox.com/1/files/sandbox/' + \
                self.key().name() + '/' + self.filename

    def get_raw_content_url(self):
        return self.raw_url

    def get_html_content_url(self):
        return self.share_url

    def get_info(self):
        bin_info = Bin.get_info(self)

        bin_info['filename'] = self.filename

        return bin_info

    @classmethod
    def get_user_id_for_token(cls, api_token):
        auth_headers = {
            'Authorization': 'Bearer ' + api_token
        }

        response = urlfetch.fetch(
                            url='https://api.dropbox.com/1/account/info',
                            headers=auth_headers,
                            deadline=URLFETCH_DEADLINE,
                            validate_certificate=URLFETCH_VALIDATE_CERTS)

        if response.status_code != 200:
            raise AppendrError(response.status_code, response.content)
        else:
            return json.loads(response.content)['uid']

    def append_data(self, params):
        auth_headers = {
            'Authorization': 'Bearer ' + self.api_token
        }

        dropbox_response = urlfetch.fetch(
                                url=self.get_dropbox_api_url(),
                                headers=auth_headers,
                                deadline=URLFETCH_DEADLINE,
                                validate_certificate=URLFETCH_VALIDATE_CERTS)

        if dropbox_response.status_code != 200:
            raise AppendrError(dropbox_response.status_code, '')

        old_content = dropbox_response.content

        new_content = append_data(old_content, self.output_format, params)

        headers = {
            'Content-Type': MIME_TYPE_JSON,
            'Authorization': 'Bearer ' + self.api_token
        }

        url = 'https://api-content.dropbox.com/1/files_put/sandbox/' + \
              self.key().name() + '/' + self.filename

        result = urlfetch.fetch(url=url,
                                payload=new_content,
                                method=urlfetch.PUT,
                                headers=headers,
                                deadline=URLFETCH_DEADLINE,
                                validate_certificate=URLFETCH_VALIDATE_CERTS)

        if result.status_code != 200:
            raise AppendrError(result.status_code, result.content)

    def initialize(self, bin_name, params):
        validate_input_param(params, 'api_token', True,
                             validate_non_empty_string,
                             False)

        validate_input_param(params, 'filename', False,
                             validate_non_empty_string,
                             DEFAULT_FILENAME % \
                                 (params['output_format'].split('/')[-1],))

        url = 'https://api-content.dropbox.com/1/files_put/sandbox/' + \
              self.key().name() + '/' + params['filename']

        headers = {
            'Content-Type': MIME_TYPE_JSON,
            'Authorization': 'Bearer ' + params['api_token']
        }

        payload = OUTPUT_FORMATS_EMPTY_DATA[params['output_format']]

        result = urlfetch.fetch(url=url,
                                payload=payload,
                                method=urlfetch.PUT,
                                headers=headers,
                                deadline=URLFETCH_DEADLINE,
                                validate_certificate=URLFETCH_VALIDATE_CERTS)

        if result.status_code != 200:
            raise AppendrError(result.status_code, '')

        self.api_token = params['api_token']
        self.filename = params['filename']

        url = 'https://api.dropbox.com/1/account/info'

        headers = {
            'Authorization': 'Bearer ' + params['api_token']
        }

        result = urlfetch.fetch(url=url,
                                method=urlfetch.GET,
                                headers=headers,
                                deadline=URLFETCH_DEADLINE,
                                validate_certificate=URLFETCH_VALIDATE_CERTS)

        json_content = json.loads(result.content)

        self.storage_user_id = json_content['uid']

        url = 'https://api.dropbox.com/1/shares/sandbox/' + \
              bin_name + '/' + params['filename']

        headers = {
            'Authorization': 'Bearer ' + params['api_token']
        }

        result = urlfetch.fetch(url=url,
                                headers=headers,
                                deadline=URLFETCH_DEADLINE,
                                validate_certificate=URLFETCH_VALIDATE_CERTS)

        json_content = json.loads(result.content)
        self.share_url = json_content['url']

        url = json_content['url']

        result = urlfetch.fetch(url=url,
                                deadline=URLFETCH_DEADLINE,
                                validate_certificate=URLFETCH_VALIDATE_CERTS)

        self.share_url = result.final_url

        html = result.content
        root = lxml.html.fromstring(html)
        a = root.xpath("//a[@id='download_button_link']")
        self.raw_url = a[0].attrib['href'][:-5]

################################################################################
# Task model
################################################################################

class Task(db.Model):
    bin = db.ReferenceProperty(Bin)
    status = db.StringProperty()
    status_msg = db.StringProperty(multiline=True)
    date_created = db.DateTimeProperty(auto_now_add=True)
    date_updated = db.DateTimeProperty(auto_now_add=True)

    @classmethod
    def generate_name(cls):
        task_name = None
        while True:
            task_name = \
                webapp2_extras.security.generate_random_string(TASK_NAME_LENGTH)

            task = Task.get_by_key_name(task_name)
            if task is None:
                break

        return task_name

    @classmethod
    def serialize(cls, tasks, bin, content_type):
        tasks_info = None

        if isinstance(tasks, Task):
            tasks_info = tasks.get_info()
        else:
            tasks_info = []
            for task in tasks:
                tasks_info.append(task.get_info())

        if content_type in [MIME_TYPE_JSON, MIME_TYPE_TEXT]:
            return json.dumps(tasks_info, indent=JSON_INDENT)
        elif content_type in [MIME_TYPE_HTML]:
            bin_info = None
            if isinstance(tasks, Task):
                template = JINJA_ENVIRONMENT.get_template(TEMPLATE_TASK)
            else:
                template = JINJA_ENVIRONMENT.get_template(TEMPLATE_TASKS)
                bin_info = bin.get_info()
            return template.render({'tasks' : tasks_info, 'bin' : bin_info})

    def get_url(self):
        return webapp2.uri_for(ROUTE_NAME_TASK_STATUS,
                               bin_name=self.bin.key().name(),
                               task_name=self.key().name(),
                               _full=True)

    def get_info(self):
        return {
          'task_id' : self.key().name(),
          'task_url' : self.get_url(),
          'tasks_url' : self.bin.get_tasks_url(),
          'bin_id' : self.bin.key().name(),
          'bin_url' : self.bin.get_url(),
          'date_created' : self.date_created.strftime(DEFAULT_DATETIME_FORMAT),
          'date_updated' : self.date_updated.strftime(DEFAULT_DATETIME_FORMAT),
          'status' : self.status,
          'status_msg' : self.status_msg
        }

################################################################################
# Handlers
################################################################################

################################################################################
# Handler for bin creation and bin search requests
################################################################################

class BinHandler(webapp2.RequestHandler):
    def options(self):
        setHTTPOptionsResponse(response=self.response,
                               oauth_methods=['GET', 'POST'])

    def get(self):
        try:
            self.response.headers.add_header('Access-Control-Allow-Origin', '*')

            accept_header = get_best_mime_match_or_default(
                self.request.headers['Accept'],
                SUPPORTED_OUTPUT_APPENDR_MIME_TYPES,
                DEFAULT_OUTPUT_APPENDR_MIME_TYPE)

            if not accept_header:
                self.error(406)
                return

            api_token = self.request.params.get('api_token', None)
            storage_backend = self.request.params.get('storage_backend', None)

            if 'api_token' is None:
                self.error(400)
                return

            if 'storage_backend' is None:
                self.error(400)
                return

            user_id = Bin.get_user_id_for_token(storage_backend, api_token)

            self.response.headers['Content-Type'] = accept_header
            bins = Bin.all().filter('storage_backend =', storage_backend)
            bins = bins.filter('storage_user_id =', user_id)
            bins = bins.order('-date_created').fetch(None)
            self.response.out.write(Bin.serialize(bins, accept_header))
        except AppendrError as e:
            self.response.set_status(e.code)
            self.response.out.write(e.msg)

    def post(self):
        try:
            self.response.headers.add_header('Access-Control-Allow-Origin', '*')
            self.response.headers.add_header('Access-Control-Expose-Headers',
                                             'Location')

            content_type = self.request.content_type

            if content_type not in SUPPORTED_APPEND_DATA_MIME_TYPES:
                self.error(415)
                return

            accept_header = get_best_mime_match_or_default(
                self.request.headers['Accept'],
                SUPPORTED_OUTPUT_APPENDR_MIME_TYPES,
                DEFAULT_OUTPUT_APPENDR_MIME_TYPE)

            if not accept_header:
                self.error(406)
                return

            params = get_request_params(self.request, content_type)
            bin = Bin.create(params)
            bin.put()

            self.response.headers['Location'] = bin.get_url()
            self.response.set_status(303)
        except AppendrError as e:
            self.response.set_status(e.code)
            self.response.out.write(e.msg)

################################################################################
# Handler for requests to a specific bin
################################################################################

class DataHandler(webapp2.RequestHandler):
    def options(self, bin_name):
        setHTTPOptionsResponse(response=self.response,
                               oauth_methods=['GET', 'POST'])

    def get(self, bin_name):
        try:
            self.response.headers.add_header('Access-Control-Allow-Origin', '*')

            accept_header = get_best_mime_match_or_default(
                self.request.headers['Accept'],
                SUPPORTED_OUTPUT_APPENDR_MIME_TYPES,
                DEFAULT_OUTPUT_APPENDR_MIME_TYPE)

            if not accept_header:
                self.error(406)
                return

            bin = Bin.get_by_key_name(bin_name)

            if (bin is None):
                self.error(404)
                return

            self.response.headers['Content-Type'] = accept_header
            self.response.set_status(200)
            self.response.out.write(Bin.serialize(bin, accept_header))
        except AppendrError as e:
            self.response.set_status(e.code)
            self.response.out.write(e.msg)

    def post(self, bin_name):
        try:
            self.response.headers.add_header('Access-Control-Allow-Origin', '*')

            bin = Bin.get_by_key_name(bin_name)

            if (bin is None):
                self.error(404)
                return

            content_type = self.request.content_type

            if content_type not in SUPPORTED_APPEND_DATA_MIME_TYPES:
                self.error(415)
                return

            params = get_request_params(self.request, content_type)
            params['date_created'] = str(datetime.utcnow())
            task_body = json.dumps(params)
            task_headers = {'Content-Type' : MIME_TYPE_JSON}

            queue_name = get_queue_name_for_bin(bin_name)
            task_name = Task.generate_name()

            task = Task(key_name=task_name)
            task.bin = bin
            task.status = TASK_STATUS_QUEUED
            task.status_msg = ''
            task.put()

            taskqueue.add(url=webapp2.uri_for(ROUTE_NAME_TASK_APPEND,
                          bin_name=bin_name),
                          queue_name=queue_name,
                          name=task_name,
                          payload=task_body,
                          headers=task_headers)

            self.response.headers['Location'] = task.get_url()
            self.response.set_status(303)
        except AppendrError as e:
            self.response.set_status(e.code)
            self.response.out.write(e.msg)

################################################################################
# Task handler for appending data to a bin
################################################################################

class AppendHandler(webapp2.RequestHandler):
    def post(self, bin_name):
        task_name = self.request.headers['X-AppEngine-TaskName']
        task = Task.get_by_key_name(task_name)

        if (task is None):
            return

        try:
            bin = Bin.get_by_key_name(bin_name)

            if (bin is None):
                return

            params = get_request_params(self.request, self.request.content_type)

            params['date_created'] = \
                dateutil.parser.parse(params['date_created'])

            bin.date_updated = params['date_created']
            bin.append_data(params)
            bin.put()

            task.date_updated = datetime.utcnow()
            task.status = TASK_STATUS_COMPLETED
            task.status_msg = ''
            task.put()

        except Exception as e:
            relativedelta = dateutil.relativedelta.relativedelta
            task.date_updated = datetime.utcnow()
            fail_count = self.request.headers['X-AppEngine-TaskExecutionCount']
            task.status_msg = ('Fail count: %s. Last error: %s' % \
                                (int(fail_count)+1, str(e)))[0:500]

            date_limit = task.date_created + \
                relativedelta(hours = TASK_RETRY_HOURS)

            if task.date_updated < date_limit:
                task.status = TASK_STATUS_RETRYING
                self.response.set_status(500)
            else:
                task.status = TASK_STATUS_FAILED
                self.response.set_status(200)

            task.put()

################################################################################
# Task handler for cleaning up unused bins
################################################################################

class BinCleanupHandler(webapp2.RequestHandler):
    def get(self):
        relativedelta = dateutil.relativedelta.relativedelta
        date_last_update = datetime.utcnow()
        date_last_update += relativedelta(hours = -1 * BIN_CLEANUP_MAX_AGE)
        unused_bins = Bin.all().order('-date_updated').filter(
            'date_updated <', date_last_update).fetch(None)

        for bin in unused_bins:
            bin.delete()

################################################################################
# Task handler for cleaning up finished tasks
################################################################################

class TaskStatusCleanupHandler(webapp2.RequestHandler):
    def get(self):
        relativedelta = dateutil.relativedelta.relativedelta
        date_last_update = datetime.utcnow()
        date_last_update += relativedelta(hours = -1 * TASK_CLEANUP_MAX_AGE)
        unchecked_tasks = Task.all().order('-date_updated').filter(
            'date_updated <', date_last_update).fetch(None)

        for task in unchecked_tasks:
            task.delete()

################################################################################
# Handler for status requests of a specific task
################################################################################

class TaskStatusHandler(webapp2.RequestHandler):
    def options(self, bin_name):
        setHTTPOptionsResponse(response=self.response)

    def get(self, bin_name, task_name):
        self.response.headers.add_header('Access-Control-Allow-Origin', '*')

        accept_header = get_best_mime_match_or_default(
                self.request.headers['Accept'],
                SUPPORTED_OUTPUT_APPENDR_MIME_TYPES,
                DEFAULT_OUTPUT_APPENDR_MIME_TYPE)

        if not accept_header:
            self.error(406)
            return

        bin = None

        if not task_name:
            bin = Bin.get_by_key_name(bin_name)

            if (bin is None):
                self.error(404)
                return

            task = Task.all().filter('bin =', bin_db_key)
            task = task.order('-date_created').fetch(None)

        else:
            task = Task.get_by_key_name(task_name)

            if (task is None):
                self.error(404)
                return

        self.response.headers['Content-Type'] = accept_header
        self.response.set_status(200)
        self.response.out.write(Task.serialize(task, bin, accept_header))

################################################################################
# Handler for the main page and root API endpoint
################################################################################

class MainHandler(webapp2.RequestHandler):
    def options(self, bin_name):
        setHTTPOptionsResponse(response=self.response)

    def get(self):
        self.response.headers.add_header('Access-Control-Allow-Origin', '*')

        accept_header = get_best_mime_match_or_default(
                self.request.headers['Accept'],
                SUPPORTED_OUTPUT_APPENDR_MIME_TYPES,
                DEFAULT_OUTPUT_APPENDR_MIME_TYPE)

        if not accept_header:
            self.error(406)
            return

        if accept_header in [MIME_TYPE_HTML]:
            template = JINJA_ENVIRONMENT.get_template(TEMPLATE_INDEX)
            resp_content = template.render()
        else:
            resp_content = json.dumps({
                'bins_url' : webapp2.uri_for(ROUTE_NAME_BINS, _full=True)
            }, indent=JSON_INDENT)

        self.response.headers['Content-Type'] = accept_header
        self.response.set_status(200)
        self.response.out.write(resp_content)

################################################################################
# Handler for creating OAuth token for GitHub Gist backend
################################################################################

class OAuthGitHubTokenHandler(webapp2.RequestHandler):
    def get(self):
        oauth_code = self.request.params.get('code')

        params = {
            'code' : oauth_code,
            'client_id' : OAUTH_GITHUB_CLIENT_ID,
            'client_secret' : OAUTH_GITHUB_CLIENT_SECRET
        }

        payload = urllib.urlencode(params)

        headers = {
            'Accept' : MIME_TYPE_JSON,
            'Content-Type' : MIME_TYPE_FORM
        }

        result = urlfetch.fetch(url='https://github.com/login/oauth/access_token',
                                payload=payload,
                                method=urlfetch.POST,
                                headers=headers,
                                deadline=URLFETCH_DEADLINE,
                                validate_certificate=URLFETCH_VALIDATE_CERTS)

        access_token = json.loads(result.content)['access_token']
        template = JINJA_ENVIRONMENT.get_template(TEMPLATE_OAUTH_TOKEN)
        resp_content = template.render({
            'service' : 'GitHub Gist',
            'token' : access_token})

        self.response.headers['Content-Type'] = 'text/html'
        self.response.set_status(200)
        self.response.out.write(resp_content)

################################################################################
# Handler for creating OAuth token for Dropbox backend
################################################################################

class OAuthDropboxTokenHandler(webapp2.RequestHandler):
    def get(self):
        oauth_code = self.request.params.get('code')

        params = {
            'code' : oauth_code,
            'grant_type' : 'authorization_code',
            'client_id' : OAUTH_DROPBOX_CLIENT_ID,
            'client_secret' : OAUTH_DROPBOX_CLIENT_SECRET,
            'redirect_uri' : 'https://appendr.appspot.com/oauth_token_dropbox'
        }

        headers = {
            'Accept' : MIME_TYPE_JSON,
            'Content-Type' : MIME_TYPE_FORM
        }

        payload = urllib.urlencode(params)

        result = urlfetch.fetch(url='https://api.dropbox.com/1/oauth2/token',
                                payload=payload,
                                method=urlfetch.POST,
                                headers=headers,
                                deadline=URLFETCH_DEADLINE,
                                validate_certificate=URLFETCH_VALIDATE_CERTS)

        access_token = json.loads(result.content)['access_token']
        template = JINJA_ENVIRONMENT.get_template(TEMPLATE_OAUTH_TOKEN)
        resp_content = template.render({
            'service' : 'Dropbox',
            'token' : access_token})

        self.response.headers['Content-Type'] = 'text/html'
        self.response.set_status(200)
        self.response.out.write(resp_content)

################################################################################
# WSGI application and routes
################################################################################

app = webapp2.WSGIApplication([
    webapp2.Route('/',
                  handler=MainHandler,
                  name=ROUTE_NAME_INDEX),

    webapp2.Route('/bins',
                  handler=BinHandler,
                  name=ROUTE_NAME_BINS),

    webapp2.Route('/bins/<bin_name:\w+>',
                  handler=DataHandler,
                  name=ROUTE_NAME_BIN),

    webapp2.Route('/bins/<bin_name:\w+>/tasks',
                  handler=TaskStatusHandler,
                  defaults={'task_name' : None},
                  name=ROUTE_NAME_TASKS),

    webapp2.Route('/bins/<bin_name:\w+>/tasks/<task_name:\w*>',
                  handler=TaskStatusHandler,
                  name=ROUTE_NAME_TASK_STATUS),

    webapp2.Route('/tasks/append/<bin_name:\w+>',
                  handler=AppendHandler,
                  name=ROUTE_NAME_TASK_APPEND),

    webapp2.Route('/tasks/cleanup_bins',
                  handler=BinCleanupHandler,
                  name=ROUTE_NAME_TASK_BIN_CLEANUP),

    webapp2.Route('/tasks/cleanup_taskstatus',
                  handler=TaskStatusCleanupHandler,
                  name=ROUTE_NAME_TASK_STATUS_CLEANUP),

    webapp2.Route('/oauth_token_github',
                  handler=OAuthGitHubTokenHandler,
                  name=ROUTE_NAME_OAUTH_GITHUB),

    webapp2.Route('/oauth_token_dropbox',
                  handler=OAuthDropboxTokenHandler,
                  name=ROUTE_NAME_OAUTH_DROPBOX)
], debug=DEBUG)
