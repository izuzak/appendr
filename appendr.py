import webapp2
import webapp2_extras.routes
import webapp2_extras.security
import jinja2
from webob.exc import *
from google.appengine.runtime import apiproxy_errors
from google.appengine.runtime import DeadlineExceededError
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
import appendr_cfg
import re
import traceback

################################################################################
# Config parameters and constants
################################################################################

# Is debugging enabled?
DEBUG = True

if DEBUG:
  logging.getLogger().setLevel(logging.DEBUG)

# How long should user agents cache CORS access control OPTIONS, in seconds
CORS_ACCESS_CONTROL_MAX_AGE = 60*60*24*30 # 30 days

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
TEMPLATE_ERROR = 'error.html'

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
DEFAULT_FILENAME = 'appendr_data.%s'

# Default message that will be set in the Gist description if the backend
# is Gist
DEFAULT_GIST_MESSAGE = ('Gist created automatically by Appendr. '
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

# Regular expression to extract dropbox share IDs from URLs
DROPBOX_ID_REGEX = re.compile(r'https://www\.dropbox\.com/s/(\w+?)/.*')

# Error messages
ERROR_MSG_NON_EMPTY_STRING_PARAM = ('Invalid value for parameter %s: %s. '
                                    'Parameter must be a non-empty string.')
ERROR_MSG_ELEMENT_OF_SET = ('Invalid value for parameter %s: %s. '
                            'Parameter must be one of: %s.')
ERROR_MSG_DEFINED = 'Parameter %s must be defined.'
ERROR_MSG_NOT_ACCEPTABLE = ('The application can not return response in the '
                           'requested mime type. Accept header was: %s. '
                           'Acceptable mime types are: %s.')

################################################################################
# Helper functions
################################################################################

def get_best_mime_match_or_default(accept_header, allowed_types, default=None):
    """ Gets the best mime type match for the accept header.

    Args:
        accept_header: value of HTTP accept header
        allowed_types: list of allowed mime types
        default: mime type to be used if accept_header is None

    Returns:
        The best mime type match, or default mime type.

    Raises:
        HTTPNotAcceptable if accept_header was defined but no match could be
        made in allowed_types.
    """

    if accept_header is None:
        return default
    else:
        match = mimeparse.best_match(allowed_types, accept_header)

        if match is None:
            raise HTTPNotAcceptable(ERROR_MSG_NOT_ACCEPTABLE % \
                  (accept_header, allowed_types))
        else:
            return match

def validate_non_empty_string(param_name, param_value):
    """ Validates that the value of a parameter is not an empty string.

    Args:
        param_name: name of parameter
        param_value: value of parameter

    Returns:
        True if param_value is a non-empty string value.

    Raises:
        HTTPClientError if param_value is an empty string or non-string type.
    """

    if not (isinstance(param_value, basestring) and param_value != ''):
        raise HTTPClientError(ERROR_MSG_NON_EMPTY_STRING_PARAM % (param_name, param_value))

def validate_element_of_list(param_name, param_value, allowed_values):
    """ Validates that the value of a parameter is a member of a list.

    Args:
        param_name: name of parameter
        param_value: value of parameter
        allowed_values: list of values that should contain param_value

    Raises:
        HTTPClientError if param_value is not a member of allowed_values
    """

    if param_value not in allowed_values:
        raise HTTPClientError(ERROR_MSG_ELEMENT_OF_SET %
                         (param_name, param_value, allowed_values))

def validate_input_param(params, param_name, must_exist,
                         validation_object, default):
    """ Validates the value of a parameter and sets default values.

    Args:
        params: dictionary-like object of parameters
        param_name: name of parameter in params that is being validated
        must_exist: whether or not the parameter must be present in params
        validation_object: function or object to be used for
                           validating the parameter
        default: the value to be used for the parameter if it doesn't exist
                 in params and it is must_exist is False

    Raises:
        HTTPClientError if must_exist is True and params do not contain a
        parameter with name param_name.
    """

    if must_exist and param_name not in params:
        raise HTTPClientError(ERROR_MSG_DEFINED % (param_name,))

    elif (must_exist and param_name in params) or \
         (not must_exist and param_name in params and params[param_name] != ''):
        if isfunction(validation_object):
            validation_object(param_name, params[param_name])
        elif isinstance(validation_object, list):
            validate_element_of_list(param_name, params[param_name], validation_object)
    else:
        params[param_name] = default

def get_request_params(request):
    """ Extracts a dictionary of params passed in the HTTP request, based on
        the content type of the request. For example, for url-encoded params
        these are just extracted from the request, but for JSON params in the
        body - these are parsed via JSON into a dict and then returned.

    Args:
        request: the HTTP request

    Returns:
        A dict of HTTP request parameters.

    Raises:
        HTTPUnsupportedMediaType if request content type is unsupported.
    """

    params = None
    if request.content_type == MIME_TYPE_FORM or request.method == 'GET':
        params = dict(request.params.copy())
    elif request.content_type == MIME_TYPE_JSON:
        params = json.loads(request.body)
    else:
        raise HTTPUnsupportedMediaType('Unsupported body mime type: ' + \
                                        request.content_type)

    logging.debug('Parsed request params: %s.' % \
                  json.dumps(params, indent=JSON_INDENT))
    return params

def get_queue_name_for_bin(bin_name):
    """ Gets the name of the task queue which stores append tasks for a
        specific bin. This is done by "sharding" tasks to queues based on
        the name of the bin.

    Args:
        bin_name: name of a bin

    Returns:
        Name of task queue responsible for storing tasks for a bin_name bin.
    """

    queue_num = sum([ord(ch) for ch in bin_name]) % NUMBER_OF_APPEND_TASK_QUEUES
    return APPEND_TASK_QUEUES_PREFIX + str(queue_num)

def get_data_csv_key_list(params):
    """ Sorts keys of a dictionary, with the creation date key in first place.
        This is used for CSV output in order to have the creation date in
        first place always, and the other keys sorted (in the same order).

    Args:
        params: dictionary object

    Returns:
        List of keys in params with 'date_created' key in first place
    """

    keys = params.keys()
    keys.remove('date_created')
    keys.sort()
    keys.insert(0, 'date_created')
    return keys

def get_dict_values_sorted(params, keys):
    """ Gets a list of dict values sorted by the order of keys in another list.

    Args:
        params: dictionary-like object
        keys: list of keys

    Returns:
        List of values in params, but sorted according to order of related keys
        in keys.
    """

    return [params.get(key) for key in keys]

def append_data_csv(old_content, params):
    """ Appends key-value data to an existing CSV document.

    Args:
        old_content: string with existing CSV data
        params: dictionary-like object with key-value data

    Returns:
        String representing CSV data that contains both old_content and params,
        where params was appended as a new row of CSV data.
    """

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

def append_data_json(old_content, params):
    """ Appends key-value data to an existing JSON document.

    Args:
        old_content: string with existing JSON data, represented as an array of
                     sets of key-value pairs (e.g. [{...}, {...}, ...])
        params: dictionary-like object with key-value data

    Returns:
        String representing JSON data that contains both old_content and params,
        where params was appended as a new element in the top-level JSON array.
    """

    json_data = json.loads(old_content)
    json_data.append(params)
    return json.dumps(json_data, indent=JSON_INDENT)

def append_data(old_content, output_format, params):
    """ Appends a key-value data to an existing document based on the format
        of the document.

    Args:
        old_content: string representing existing data/document
        output_format: mime type format of the document
        params: dictionary-like object with key-value data

    Returns:
        String document with existing and new data appended.

    Raises:
        HTTPServerError if output_format is unsupported by application.
    """

    params['date_created'] = \
        params['date_created'].strftime(DEFAULT_DATETIME_FORMAT)

    logging.debug('Appending data:\n%s' % json.dumps({
      'old_data' : old_content,
      'new_data' : params,
      'output_format' : output_format
    }, indent=JSON_INDENT))

    if output_format == MIME_TYPE_CSV:
        return append_data_csv(old_content, params)

    elif output_format == MIME_TYPE_JSON:
        return append_data_json(old_content, params)

    else:
        # will actually never happen since we catch this before
        raise HTTPServerError('Invalid output format: %s' % (output_format),)

def setHTTPOptionsResponse(response,
                           cors_origin='*',
                           cors_methods=['GET'],
                           cors_headers=['Content-Type']):
    """ Constructs the response to HTTP OPTIONS request.

    Args:
        response: the HTTP response object
        cors_origin: domains for which cross-domains should be allowed via
                     CORS
        cors_methods: list of methods to be allowed via CORS and regular HTTP
        cors_headers: list of HTTP headers to be exposed to cross-domain calls
    """

    headers = response.headers
    headers.add_header('Access-Control-Allow-Origin', cors_origin)
    headers.add_header('Access-Control-Allow-Methods', ', '.join(cors_methods))
    headers.add_header('Access-Control-Allow-Headers', ', '.join(cors_headers))
    headers.add_header('Access-Control-Max-Age', CORS_ACCESS_CONTROL_MAX_AGE)
    headers.add_header('Allow', ', '.join(['OPTIONS'] + cors_methods))
    response.set_status(200)

def extractHTTPerrorInfo(request, response, exception):
    """ Extracts request/response information for error handling.

    Args:
        request: HTTP request object
        response: HTTP response object
        exception: Exception that occurred during request processing.

    Returns:
        Dictionary with information for error handling: request url ("url"),
        request HTTP method ("method"), request body ("body"), request headers
        ("headers"), response code ("response_code"), response title
        ("response_title"), details about the error ("details") and the
        exception stack trace ("stack_trace").
    """
    info = dict()

    info['url'] = request.url
    info['method'] = request.method
    info['body'] = request.body
    info['headers'] = dict(request.headers)
    info['response_code'] = exception.code
    info['response_title'] = exception.title
    info['details'] = str(exception)
    info['stack_trace'] = traceback.format_exc()

    return info

def serialize_error(mime_type, error_info):
    """ Serialization of error handling information based on mime type.

    Args:
        mime_type: mime type to serialize error info to
        error_info: information about an exception that happened

    Returns:
        String representing the error_info in mime_type.

    Raises:
        HTTPNotAcceptable if mime_type is not supported by application.
    """

    if mime_type == MIME_TYPE_HTML:
        template = JINJA_ENVIRONMENT.get_template(TEMPLATE_ERROR)
        return template.render(error_info)

    elif mime_type in [MIME_TYPE_JSON, MIME_TYPE_TEXT]:
        return json.dumps(error_info)

    else:
        # should never happen because it is detected earlier
        raise HTTPNotAcceptable(ERROR_MSG_NOT_ACCEPTABLE % \
                  (accept_header, allowed_types))

def handle_error(request, response, exception):
    """ Handler for all exception thrown by application. Extracts the error
        info, logs it, serializes into into an acceptable mime type and returns
        to the client.

    Args:
        request: HTTP request
        response: HTTP response
        exception: exception that occurred during request processing
    """
    logging.exception('Error while processing request.\n%s' % json.dumps({
                       'request_body' : request.body,
                       'request_headers' : dict(request.headers)},
                       indent=JSON_INDENT))

    accept_header = None
    try:
        accept_header = get_best_mime_match_or_default(
                request.headers.get('Accept'),
                SUPPORTED_OUTPUT_APPENDR_MIME_TYPES,
                DEFAULT_OUTPUT_APPENDR_MIME_TYPE)
    except HTTPNotAcceptable as e:
        accept_header = MIME_TYPE_HTML

    if isinstance(exception, apiproxy_errors.OverQuotaError):
        pass

    elif isinstance(exception, DeadlineExceededError):
        pass

    if not isinstance(exception, webapp2.HTTPException):
        exception = HTTPInternalServerError(detail=str(exception))

    error_info = extractHTTPerrorInfo(request, response, exception)
    content = serialize_error(accept_header, error_info)

    response.set_status(exception.code)
    response.headers['Content-Type'] = accept_header
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.out.write(content)

################################################################################
# Base Bin model
################################################################################

class Bin(polymodel.PolyModel):
    """ Represents the base (abstract) class for bins, where subclasses are
        implemented for each supported backend service.
    """

    date_created = db.DateTimeProperty(auto_now_add=True)
    date_updated = db.DateTimeProperty(auto_now_add=True)
    output_format = db.StringProperty()
    storage_backend = db.StringProperty()
    storage_user_id = db.StringProperty()

    def get_url(self):
        """ Constructs the URL for this bin resource.

        Returns:
            String representation of full URL of this bin.
        """

        return webapp2.uri_for(ROUTE_NAME_BIN,
                               bin_name=self.key().name(),
                               _full=True)

    def get_tasks_url(self):
        """ Constructs the URL for the tasks resource of this bin.

        Returns:
            String representation of full URL for the task resource of this bin.
        """

        return webapp2.uri_for(ROUTE_NAME_TASKS,
                               bin_name=self.key().name(),
                               _full=True)

    def get_raw_content_url(self):
        """ (Abstract) Constructs the URL for the raw contents associated with
            this bin. This URL will be on the domain of the external storage
            service. Subclasses of Bin must/should implement this method.
        """

        return None

    def get_html_content_url(self):
        """ (Abstract) Constructs the URL for the HTML contents associated with
            this bin. This URL will be on the domain of the external storage
            service. Subclasses of Bin must/should implement this method.
        """

        return None

    def get_info(self):
        """ Constructs the information about this bin resource that is sent
            over the network to clients.

        Returns:
            Dictionary of bin properties and tasks.
        """

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
        """ Generates a unique name for a Bin.

        Returns:
            String representing a unique name for a bin, where unique means
            with respect to all other Bin instances stored in the datastore.
        """

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
        """ Serializes a Bin or list of Bins based on the desired output
            mime type.

        Args:
            bins: a Bin instance or list of Bins
            content_type: mime type to which bins should be serialized

        Returns:
            String representation of bins in content_type format.

        Raises:
            HTTPNotAcceptable is content_type is not supported by application.
        """

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
        else:
            # should never happen because it is detected earlier
            raise HTTPNotAcceptable(ERROR_MSG_NOT_ACCEPTABLE % \
                      (content_type, SUPPORTED_OUTPUT_APPENDR_MIME_TYPES))


    @classmethod
    def get_user_id_for_token(cls, storage_backend, api_token):
        """ Gets the user id for an OAuth token of a specific backend storage
            service. The user id is specific for the storage backend so this
            method delegated to a subclass that will fetch this id via an
            API call to the backend service.

        Args:
            storage_backend: id of the backend storage service for which the
                             API token is valid.
            api_token: OAuth API token for a backend storage service.

        Returns:
            String representation of user id associated with api_token.

        Raises:
            HTTPClientError if storage_backend is not supported by application.
        """

        if storage_backend == STORAGE_BACKEND_GIST:
            return GistBin.get_user_id_for_token(api_token)
        elif storage_backend == STORAGE_BACKEND_DROPBOX:
            return DropboxBin.get_user_id_for_token(api_token)
        else:
            # should never happen since detected earlier
            raise HTTPClientError('Unsupported storage service: ' + \
                                  storage_backend)

    @classmethod
    def create(cls, params):
        """ Creates a Bin from input parameters. This method delegates to
            subclasses to finish parameter validation, bin creation and
            initialization.

        Args:
            params: a dictionary-like object with parameters for creating
            a Bin. Parameters may vary based on backend storage service used
            for this Bin.

        Returns:
            Bin instance which has not been written to datastore.

        Raises:
            HTTPClientError if parameters define a storage backend that is
            not supported by the application.
        """

        validate_input_param(params, 'storage_backend', False,
                             SUPPORTED_STORAGE_BACKENDS.keys(),
                             DEFAULT_STORAGE_BACKEND)

        validate_input_param(params, 'output_format', False,
                             SUPPORTED_OUTPUT_EXTERNAL_DATA_MIME_TYPES,
                             DEFAULT_OUTPUT_EXTERNAL_DATA_MIME_TYPE)

        bin_name = Bin.generate_name()
        bin = None

        logging.debug('Creating bin %s.' % (bin_name,))

        if params['storage_backend'] == STORAGE_BACKEND_GIST:
            bin = GistBin(key_name=bin_name)
        elif params['storage_backend'] == STORAGE_BACKEND_DROPBOX:
            bin = DropboxBin(key_name=bin_name)
        else:
            # should never happen since detected earlier
            raise HTTPClientError('Unsupported storage service: ' + \
                                  storage_backend)

        bin.output_format = params['output_format']
        bin.storage_backend = params['storage_backend']
        bin.initialize(bin_name, params)

        return bin

################################################################################
# GistBin model
################################################################################

class GistBin(Bin):
    """ A Bin implementation that uses GitHub Gists for storing data. """

    is_public = db.BooleanProperty()
    gist_id = db.StringProperty()
    api_token = db.StringProperty()
    filename = db.StringProperty()

    def get_gist_api_url(self):
        """ Constructs the URL for fetching the representation of the
            gist that stores the data for this bin, via the GitHub API.

        Returns:
            String representation of GitHub API resource that stores the data
            for this bin.
        """

        return 'https://api.github.com/gists/' + self.gist_id

    def get_raw_content_url(self):
        """ Implementation of the Bin abstract method.

        Returns:
            String representation of URL of resource on GitHub domain that
            contains the raw data for this Bin.
        """

        return 'https://gist.github.com/raw/' + self.gist_id + \
                '/' + self.filename

    def get_html_content_url(self):
        """ Implementation of the Bin abstract method.

        Returns:
            String representation of URL of resource on GitHub domain that
            contains the HTML page with data for this Bin.
        """

        return 'https://gist.github.com/' + self.gist_id

    def get_info(self):
        """ Constructs the information about this GistBin resource that is sent
            over the network to clients. First constructs the generic Bin
            information and the adds GistBin specific information.

        Returns:
            Dictionary of bin properties and tasks.
        """

        bin_info = Bin.get_info(self)

        bin_info['is_public'] = self.is_public
        bin_info['gist_id'] = self.gist_id
        bin_info['filename'] = self.filename
        bin_info['gist_api_url'] = self.get_gist_api_url()

        return bin_info

    @classmethod
    def get_user_id_for_token(cls, api_token):
        """ Retrieves the user id for a GitHub OAuth token.

        Args:
            api_token: OAuth token for GitHub API.

        Returns:
            String representation of GitHub user id associated with api_token.
        """

        auth_headers = {
            'Authorization': 'token ' + api_token
        }

        response = urlfetch.fetch(
                            url='https://api.github.com/user',
                            headers=auth_headers,
                            deadline=URLFETCH_DEADLINE,
                            validate_certificate=URLFETCH_VALIDATE_CERTS)

        if response.status_code != 200:
            raise status_map[response.status_code](\
                'Error while calling GitHub API - fetch user information\n' + \
                response.content)
        else:
            return str(json.loads(response.content)['id'])

    def append_data(self, params):
        """ Appends data to a Gist. Works by fetching existing data, then
            appending new data locally and writing the results back to the Gist.

        Args:
            params: dictionary-like object with key-value data to be appended
                    to existing data

        Raises:
            HTTPError if GitHub API invocation failed.
        """

        auth_headers = {
            'Authorization': 'token ' + self.api_token
        }

        gist_response = urlfetch.fetch(
                            url=self.get_gist_api_url(),
                            headers=auth_headers,
                            deadline=URLFETCH_DEADLINE,
                            validate_certificate=URLFETCH_VALIDATE_CERTS)

        if gist_response.status_code != 200:
            raise status_map[gist_response.status_code](\
                'Error while calling GitHub API - fetch gist data\n' + \
                response.content)

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
            raise status_map[result.status_code](\
                'Error while calling GitHub API - update gist data\n' + \
                response.content)

    def initialize(self, bin_name, params):
        """ Initializes a GistBin by creating a GitHub gist and writing
            initial data since files in a gist can't be empty.

        Args:
            bin_name: name of the Bin to be initialized (not used here)
            params: dictionary-like object with parameters relevant for
                    GistBin creation

        Raises:
            HTTPError if GitHub API invocations failed.
        """

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
            raise status_map[result.status_code](\
                'Error while calling GitHub API - create gist\n' + \
                result.content)

        json_content = json.loads(result.content)

        self.is_public = params['is_public']
        self.gist_id = json_content['id']
        self.api_token = params['api_token']
        self.filename = params['filename']
        self.storage_user_id = str(json_content['user']['id'])

################################################################################
# DropboxBin model
################################################################################

class DropboxBin(Bin):
    """ A Bin implementation that uses Dropbox for storing data. """

    api_token = db.StringProperty()
    filename = db.StringProperty()
    dropbox_id = db.StringProperty()

    def get_dropbox_api_url(self):
        """ Constructs the URL for fetching the representation of the
            gist that stores the data for this bin, via the Dropbox API.

        Returns:
            String representation of Dropbox API resource that stores the data
            for this bin.
        """

        return 'https://api-content.dropbox.com/1/files/sandbox/' + \
                self.key().name() + '/' + self.filename

    def get_raw_content_url(self):
        """ Implementation of the Bin abstract method.

        Returns:
            String representation of URL of resource on Dropbox domain that
            contains the raw data for this Bin.
        """

        return 'https://dl.dropboxusercontent.com/s/' + \
                self.dropbox_id + '/' + self.filename

    def get_html_content_url(self):
        """ Implementation of the Bin abstract method.

        Returns:
            String representation of URL of resource on Dropbox domain that
            contains the HTML page with data for this Bin.
        """

        return 'https://www.dropbox.com/s/' + \
                self.dropbox_id + '/' + self.filename

    def get_info(self):
        """ Constructs the information about this DropboxBin resource that is
            sent over the network to clients. First constructs the generic Bin
            information and the adds DropboxBin specific information.

        Returns:
            Dictionary of bin properties and tasks.
        """

        bin_info = Bin.get_info(self)
        bin_info['filename'] = self.filename

        return bin_info

    @classmethod
    def get_user_id_for_token(cls, api_token):
        """ Retrieves the user id for a Dropbox OAuth token.

        Args:
            api_token: OAuth token for Dropbox API.

        Returns:
            String representation of Dropbox user id associated with api_token.
        """

        auth_headers = {
            'Authorization': 'Bearer ' + api_token
        }

        response = urlfetch.fetch(
                            url='https://api.dropbox.com/1/account/info',
                            headers=auth_headers,
                            deadline=URLFETCH_DEADLINE,
                            validate_certificate=URLFETCH_VALIDATE_CERTS)

        if response.status_code != 200:
            raise status_map[response.status_code](\
                'Error while calling Dropbox API - fetch account info\n' + \
                response.content)
        else:
            return str(json.loads(response.content)['uid'])

    def append_data(self, params):
        """ Appends data to a Dropbox file. Works by fetching existing data,
            then appending new data locally and writing the results back to the
            file on Dropbox.

        Args:
            params: dictionary-like object with key-value data to be appended
                    to existing data

        Raises:
            HTTPError if a Dropbox API invocation fails.
        """

        auth_headers = {
            'Authorization': 'Bearer ' + self.api_token
        }

        dropbox_response = urlfetch.fetch(
                                url=self.get_dropbox_api_url(),
                                headers=auth_headers,
                                deadline=URLFETCH_DEADLINE,
                                validate_certificate=URLFETCH_VALIDATE_CERTS)

        if dropbox_response.status_code != 200:
            raise status_map[dropbox_response.status_code](\
                'Error while calling Dropbox API - fetch file data\n' + \
                dropbox_response.content)

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
            raise status_map[result.status_code](\
                'Error while calling Dropbox API - update file data\n' + \
                result.content)

    def initialize(self, bin_name, params):
        """ Initializes a DropboxBin by:
            1) creating a folder on Dropbox named by the bin name
            2) creating a file in the folder with the initial data
            3) fetching the publicly shareable URL for this file
            4) resolving the publicly shareable URL to get to the Dropbox id
               for this file. The publicly shareable URL is shortened, so it
               has to be resolved in order to get the final URL which contains
               the id.

        Args:
            bin_name: name of the Bin to be initialized (not used here)
            params: dictionary-like object with parameters relevant for
                    DropboxBin creation

        Raises:
            HTTPError if a Dropbox API invocation fails.
        """
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
            raise status_map[result.status_code](\
                'Error while calling Dropbox API - create file\n' + \
                result.content)

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

        if result.status_code != 200:
            raise status_map[result.status_code](\
                'Error while calling Dropbox API - fetch account info\n' + \
                result.content)

        json_content = json.loads(result.content)
        self.storage_user_id = str(json_content['uid'])

        url = 'https://api.dropbox.com/1/shares/sandbox/' + \
              bin_name + '/' + params['filename']

        headers = {
            'Authorization': 'Bearer ' + params['api_token']
        }

        result = urlfetch.fetch(url=url,
                                headers=headers,
                                deadline=URLFETCH_DEADLINE,
                                validate_certificate=URLFETCH_VALIDATE_CERTS)

        if result.status_code != 200:
            raise status_map[result.status_code](\
                'Error while calling Dropbox API - get file public URL\n' + \
                result.content)

        json_content = json.loads(result.content)
        self.share_url = json_content['url']

        url = json_content['url']

        result = urlfetch.fetch(url=url,
                                deadline=URLFETCH_DEADLINE,
                                validate_certificate=URLFETCH_VALIDATE_CERTS)

        if result.status_code != 200:
            raise status_map[result.status_code](\
                'Error while calling Dropbox API - retrieve shared file\n' + \
                result.content)

        # The line below extracts the ID of the file on dropbox so that
        # it can be used to construct raw content and html content URLs
        # as described here: https://www.dropbox.com/help/201/en
        self.dropbox_id = DROPBOX_ID_REGEX.match(result.final_url).group(1)

################################################################################
# Task model
################################################################################

class Task(db.Model):
    """ A task for appending data to a Bin. """

    bin = db.ReferenceProperty(Bin)
    status = db.StringProperty()
    status_msg = db.StringProperty(multiline=True)
    date_created = db.DateTimeProperty(auto_now_add=True)
    date_updated = db.DateTimeProperty(auto_now_add=True)

    @classmethod
    def generate_name(cls):
        """ Generates a unique name for a Task.

        Returns:
            String representing a unique name for a Task, where unique means
            with respect to all other Task instances stored in the datastore.
        """

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
        """ Serializes a Task or list of Tasks based on the desired output
            mime type.

        Args:
            tasks: a Task instance or list of Tasks
            bin: the Bin that tasks belong to
            content_type: mime type to which tasks should be serialized

        Returns:
            String representation of tasks in content_type format.

        Raises:
            HTTPNotAcceptable is content_type is not supported by application.
        """

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
        """ Constructs the URL for this Task resource.

        Returns:
            String representation of full URL of this Task.
        """

        return webapp2.uri_for(ROUTE_NAME_TASK_STATUS,
                               bin_name=self.bin.key().name(),
                               task_name=self.key().name(),
                               _full=True)

    def get_info(self):
        """ Constructs the information about this Task resource that is sent
            over the network to clients.

        Returns:
            Dictionary of Task properties.
        """

        return {
          'task_id' : self.key().name(),
          'task_url' : self.get_url(),
          'tasks_url' : self.bin.get_tasks_url(),
          'bin_id' : self.bin.key().name(),
          'bin_url' : self.bin.get_url(),
          'date_created' : self.date_created.strftime(DEFAULT_DATETIME_FORMAT),
          'date_updated' : self.date_updated.strftime(DEFAULT_DATETIME_FORMAT),
          'datetime_format' : DEFAULT_DATETIME_FORMAT,
          'status' : self.status,
          'status_msg' : self.status_msg
        }

################################################################################
# Handlers
################################################################################

class BinHandler(webapp2.RequestHandler):
    """ Handler for bin creation and bin search requests. """

    def options(self):
        setHTTPOptionsResponse(response=self.response,
                               oauth_methods=['GET', 'POST'])

    def get(self):
        """ Returns bins associated with a specific storage backend and user
            (based on OAuth API token for that backend).
        """

        self.response.headers.add_header('Access-Control-Allow-Origin', '*')

        accept_header = get_best_mime_match_or_default(
            self.request.headers.get('Accept'),
            SUPPORTED_OUTPUT_APPENDR_MIME_TYPES,
            DEFAULT_OUTPUT_APPENDR_MIME_TYPE)

        validate_input_param(self.request.params, 'api_token', True,
                             validate_non_empty_string,
                             False)

        validate_input_param(self.request.params, 'storage_backend', True,
                             validate_non_empty_string,
                             False)

        api_token = self.request.params.get('api_token')
        storage_backend = self.request.params.get('storage_backend')

        user_id = Bin.get_user_id_for_token(storage_backend, api_token)
        bins = Bin.all().filter('storage_backend =', storage_backend)
        bins = bins.filter('storage_user_id =', user_id)
        bins = bins.order('-date_created').fetch(None)

        self.response.headers['Content-Type'] = accept_header
        self.response.out.write(Bin.serialize(bins, accept_header))

    def post(self):
        """ Creates a bin based on passed paramters and returns a
            representation of the created bin.
        """

        self.response.headers.add_header('Access-Control-Allow-Origin', '*')
        self.response.headers.add_header('Access-Control-Expose-Headers',
                                         'Location')

        accept_header = get_best_mime_match_or_default(
            self.request.headers.get('Accept'),
            SUPPORTED_OUTPUT_APPENDR_MIME_TYPES,
            DEFAULT_OUTPUT_APPENDR_MIME_TYPE)

        params = get_request_params(self.request)
        bin = Bin.create(params)
        bin.put()

        self.response.headers['Location'] = bin.get_url()

        if accept_header == MIME_TYPE_HTML:
            self.response.set_status(303)
        else:
            self.response.set_status(201)
            self.response.out.write(Bin.serialize(bin, accept_header))

class DataHandler(webapp2.RequestHandler):
    """ Handler for requests to a specific bin. """

    def options(self, bin_name):
        setHTTPOptionsResponse(response=self.response,
                               oauth_methods=['GET', 'POST'])

    def get(self, bin_name):
        """ Returns a representation of a specific bin.

        Args:
            bin_name: name of bin that is being fetched
        """

        self.response.headers.add_header('Access-Control-Allow-Origin', '*')

        accept_header = get_best_mime_match_or_default(
            self.request.headers.get('Accept'),
            SUPPORTED_OUTPUT_APPENDR_MIME_TYPES,
            DEFAULT_OUTPUT_APPENDR_MIME_TYPE)

        bin = Bin.get_by_key_name(bin_name)

        if (bin is None):
            raise HTTPNotFound()

        self.response.headers['Content-Type'] = accept_header
        self.response.set_status(200)
        self.response.out.write(Bin.serialize(bin, accept_header))

    def post(self, bin_name):
        """ Creates an append data task for specific bin. Tasks are enqueued
            to task queues via a sharding "algorithm".

        Args:
            bin_name: name of bin to which data should be appended to
        """

        self.response.headers.add_header('Access-Control-Allow-Origin', '*')

        accept_header = get_best_mime_match_or_default(
            self.request.headers.get('Accept'),
            SUPPORTED_OUTPUT_APPENDR_MIME_TYPES,
            DEFAULT_OUTPUT_APPENDR_MIME_TYPE)

        bin = Bin.get_by_key_name(bin_name)

        if (bin is None):
            raise HTTPNotFound()

        params = get_request_params(self.request)
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

        logging.debug('Added task %s for bin %s to queue %s.' % \
                      (task_name, bin_name, queue_name))

        self.response.headers['Location'] = task.get_url()

        if accept_header == MIME_TYPE_HTML:
            self.response.set_status(303)
        else:
            self.response.set_status(202)
            self.response.out.write(Task.serialize(task, bin, accept_header))

class AppendHandler(webapp2.RequestHandler):
    """ Task handler for appending data to a bin. """

    def post(self, bin_name):
        """ Appends data to a specific bin. Appending is retried if it fails
            until a predefined timeout occurs.

        Args:
            bin_name: name of bin to which data should be appended to
        """

        task_name = self.request.headers['X-AppEngine-TaskName']
        task = Task.get_by_key_name(task_name)

        if (task is None):
            return

        try:
            bin = Bin.get_by_key_name(bin_name)

            if (bin is None):
                return

            params = get_request_params(self.request)
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

            logging.exception('Error while appending data. ' +\
                              'Task name: %s.' % (task_name,) +\
                              'Task fail count: %s' % (fail_count,))

            date_limit = task.date_created + \
                relativedelta(hours = TASK_RETRY_HOURS)

            if task.date_updated < date_limit:
                task.status = TASK_STATUS_RETRYING
                self.response.set_status(500)
            else:
                task.status = TASK_STATUS_FAILED
                self.response.set_status(200)

            task.put()

class BinCleanupHandler(webapp2.RequestHandler):
    """ Task handler for cleaning up unused bins. """

    def get(self):
        """ Retrieves bins that have not been updated for a specific time
            and deletes them from the datastore.
        """

        relativedelta = dateutil.relativedelta.relativedelta
        date_last_update = datetime.utcnow()
        date_last_update += relativedelta(hours = -1 * BIN_CLEANUP_MAX_AGE)
        unused_bins = Bin.all().order('-date_updated').filter(
            'date_updated <', date_last_update).fetch(None)

        logging.debug("Cleanup job is deleting %s bins." % len(unused_bins))

        for bin in unused_bins:
            bin.delete()

class TaskStatusCleanupHandler(webapp2.RequestHandler):
    """ Task handler for cleaning up finished data append tasks. """

    def get(self):
        """ Retrieves tasks that have not been updated for a specific time
            and deletes them from the datastore.
        """

        relativedelta = dateutil.relativedelta.relativedelta
        date_last_update = datetime.utcnow()
        date_last_update += relativedelta(hours = -1 * TASK_CLEANUP_MAX_AGE)
        unchecked_tasks = Task.all().order('-date_updated').filter(
            'date_updated <', date_last_update).fetch(None)

        logging.debug("Cleanup job is deleting %s tasks." % len(unchecked_tasks))

        for task in unchecked_tasks:
            task.delete()

class TaskStatusHandler(webapp2.RequestHandler):
    """ Handler for status requests of a specific task. """

    def options(self, bin_name):
        setHTTPOptionsResponse(response=self.response)

    def get(self, bin_name, task_name):
        """ Returns a representation of a specific task.

        Args:
            bin_name: name of bin that is associated with the task being fetched
            task_name: name of task that is being fetched
        """

        self.response.headers.add_header('Access-Control-Allow-Origin', '*')

        accept_header = get_best_mime_match_or_default(
                self.request.headers.get('Accept'),
                SUPPORTED_OUTPUT_APPENDR_MIME_TYPES,
                DEFAULT_OUTPUT_APPENDR_MIME_TYPE)

        bin = None

        if not task_name:
            bin = Bin.get_by_key_name(bin_name)

            if (bin is None):
                raise HTTPNotFound()

            task = Task.all().filter('bin =', bin_db_key)
            task = task.order('-date_created').fetch(None)

        else:
            task = Task.get_by_key_name(task_name)

            if (task is None):
                raise HTTPNotFound()

        self.response.headers['Content-Type'] = accept_header
        self.response.set_status(200)
        self.response.out.write(Task.serialize(task, bin, accept_header))

class MainHandler(webapp2.RequestHandler):
    """ Handler for the main page and root API endpoint. """

    def options(self, bin_name):
        setHTTPOptionsResponse(response=self.response)

    def get(self):
        """ Returns the index page for the application or a JSON response
            with a link to resource for creating bins.
        """

        self.response.headers.add_header('Access-Control-Allow-Origin', '*')

        accept_header = get_best_mime_match_or_default(
                self.request.headers.get('Accept'),
                SUPPORTED_OUTPUT_APPENDR_MIME_TYPES,
                DEFAULT_OUTPUT_APPENDR_MIME_TYPE)

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

class OAuthGitHubTokenHandler(webapp2.RequestHandler):
    """ Handler for creating OAuth token for GitHub Gist backend. """

    def get(self):
        """ Returns an HTML page with the OAuth API token for GitHub. The
            token is first retrieved by calling GitHub's API with a code
            that was passed in when the user was redirected to this page
            as a part of the OAuth flow.
        """

        accept_header = get_best_mime_match_or_default(
                self.request.headers.get('Accept'),
                [MIME_TYPE_HTML],
                MIME_TYPE_HTML)

        params = get_request_params(self.request)
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

        result = urlfetch.fetch(
                    url='https://github.com/login/oauth/access_token',
                    payload=payload,
                    method=urlfetch.POST,
                    headers=headers,
                    deadline=URLFETCH_DEADLINE,
                    validate_certificate=URLFETCH_VALIDATE_CERTS)

        if result.status_code != 200:
            raise status_map[result.status_code](\
                'Error while creating GitHub OAuth token. \n' + result.content)

        access_token = json.loads(result.content)['access_token']
        template = JINJA_ENVIRONMENT.get_template(TEMPLATE_OAUTH_TOKEN)
        resp_content = template.render({
            'service' : 'GitHub Gist',
            'token' : access_token})

        self.response.headers['Content-Type'] = 'text/html'
        self.response.set_status(200)
        self.response.out.write(resp_content)

class OAuthDropboxTokenHandler(webapp2.RequestHandler):
    """ Handler for creating OAuth token for Dropbox backend. """

    def get(self):
        """ Returns an HTML page with the OAuth API token for Dropbox. The
            token is first retrieved by calling Dropbox's API with a code
            that was passed in when the user was redirected to this page
            as a part of the OAuth flow.
        """

        accept_header = get_best_mime_match_or_default(
                self.request.headers.get('Accept'),
                [MIME_TYPE_HTML],
                MIME_TYPE_HTML)

        params = get_request_params(self.request)
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

        if result.status_code != 200:
            raise status_map[result.status_code](\
                'Error while creating Dropbox OAuth token. \n' + result.content)

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

# Register the error handler with specific HTTP error codes
for error_code in [400, 401, 403,404, 405, 406, 415, 500, 501, 503]:
    app.error_handlers[error_code] = handle_error
