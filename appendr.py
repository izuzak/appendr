import webapp2
import webapp2_extras.routes
import webapp2_extras.security
from google.appengine.api import urlfetch
from google.appengine.api import taskqueue
from google.appengine.ext import db
from google.appengine.ext.db import polymodel
from datetime import datetime
from inspect import isfunction
import json
import cStringIO
import csv
import mimeparse
import copy
import dateutil.parser
import dateutil.relativedelta


#
# HELPERS
#

class AppendrError(Exception):
    def __init__(self, code, msg):
        Exception.__init__(self, msg)
        self.code = code
        self.msg = msg

def validate_non_empty_string(name, value):
    if not (isinstance(value, basestring) and value != ""):
        raise ValueError("Invalid value for parameter %r: %r. Parameter should be a non-empty string." % (name, value))

def validate_element_of_list(name, value, possible_values):
    if value not in possible_values:
        raise ValueError("Invalid value for parameter %r: %r. Parameter should be one of: %r." % (name, value, possible_values))

def validate_input_param(params, name, must_exist, validation_object, default):
    if must_exist and name not in params:
        raise ValueError("Parameter %r must be defined." % (name))

    if name in params:
        if isfunction(validation_object):
            validation_object(name, params[name])
        elif isinstance(validation_object, list):
            validate_element_of_list(name, params[name], validation_object)
    else:
        params[name] = default

    return params

def get_data_csv_key_list(params):
    keys = params.keys()
    keys.remove('date_created')
    keys.sort()
    keys.insert(0, 'date_created')
    return keys

def get_request_params(req, content_type):
  if content_type == 'application/x-www-form-urlencoded':
      return dict(req.params.copy())
  elif content_type == 'application/json':
      return json.loads(req.body)

def get_values_sorted(keys, params):
  data = []
  for key in keys:
      data.append(params[key])
  return data

def serialize_bins(bins, content_type):
    key_list = ["date_created", "date_updated", "bin_id", "bin_url", "output_format", "datetime_format", "storage_backend"]

    bins_json = []
    for bin in bins:
        bins_json.append({
            "bin_id" : bin.key().name(),
            "bin_url" : bin.get_url(),
            "date_created" : bin.date_created.strftime(bin.datetime_format),
            "date_updated" : bin.date_updated.strftime(bin.datetime_format),
            "output_format" : bin.output_format,
            "datetime_format" : bin.datetime_format,
            "storage_backend" : bin.storage_backend
        })
    if content_type in ['application/json', 'text/plain']:
        return json.dumps(bins_json, indent=2)


def append_data_(old_content, output_format, datetime_format, params):
    params['date_created'] = params['date_created'].strftime(datetime_format)

    if output_format == 'csv':
        key_list = get_data_csv_key_list(params)

        output = cStringIO.StringIO()
        csv_writer = csv.writer(output, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)

        if old_content == output_data_formats_empty_string['csv']:
            csv_writer.writerow(key_list)

        data = get_values_sorted(key_list, params)
        csv_writer.writerow(data)

        if old_content == output_data_formats_empty_string['csv']:
            return output.getvalue()
        else:
            return old_content+output.getvalue()

    elif output_format =='json':
        json_data = json.loads(old_content)
        json_data.append(params)
        return json.dumps(json_data, indent=2)

def compute_queue_number_from_bin_id(bin_id, num_queues):
    queue_num = 0
    for ch in bin_id:
        queue_num = (queue_num + ord(ch)) % num_queues

    return "queue" + str(queue_num)

#
# MODELS
#

class Bin(polymodel.PolyModel):
    date_created = db.DateTimeProperty(auto_now_add=True)
    date_updated = db.DateTimeProperty(auto_now_add=True)
    output_format = db.StringProperty()
    datetime_format = db.StringProperty()
    storage_backend = db.StringProperty()

    def get_url(self):
        return webapp2.uri_for('bin', bin_key=self.key().name(), _full=True)

    @classmethod
    def generate_name(cls):
        bin_name = None
        while True:
            bin_name = webapp2_extras.security.generate_random_string(20)

            bin = Bin.get_by_key_name(bin_name)
            if bin is None:
                  break

        return bin_name

    @classmethod
    def create(cls, params):
        validate_input_param(params, 'storage_backend', False, storage_backends.keys(), 'gist')
        validate_input_param(params, 'output_format', False, output_data_formats, 'json')
        validate_input_param(params, 'datetime_format', False, validate_non_empty_string, '%Y-%m-%dT%H:%M:%SZ')

        bin_class = storage_backends[params['storage_backend']]
        bin_name = Bin.generate_name()
        bin = bin_class(key_name=bin_name)

        bin.output_format = params['output_format']
        bin.datetime_format = params['datetime_format']
        bin.storage_backend = params['storage_backend']
        bin.initialize(bin_name, params)

        return bin

class GistBin(Bin):
    is_public = db.BooleanProperty()
    gist_id = db.StringProperty()
    api_token = db.StringProperty()
    filename = db.StringProperty()

    def get_gist_url(self):
        return "https://api.github.com/gists/" + self.gist_id

    def append_data(self, params):
        auth_headers = {
            "Authorization": 'token ' + self.api_token
        }

        gist_response = urlfetch.fetch(url=self.get_gist_url(), headers=auth_headers)

        if gist_response.status_code != 200:
            raise AppendrError(gist_response.status_code, "")

        json_gist = json.loads(gist_response.content)

        raw_file_response = urlfetch.fetch(
                                  url=json_gist['files'][self.filename]['raw_url'],
                                  headers=auth_headers)

        if raw_file_response.status_code != 200:
            raise AppendrError(raw_file_response.status_code, "")

        new_content = append_data_(raw_file_response.content, self.output_format, self.datetime_format, params)

        new_payload = json.dumps({
            "files" : {
                self.filename : {
                    "content" : new_content
                }
            }
        })

        gist_headers = {
            'Content-Type': 'application/json',
            "Authorization": 'token ' + self.api_token
        }

        result = urlfetch.fetch(url=self.get_gist_url(),
                        payload=new_payload,
                        method=urlfetch.POST,
                        headers=gist_headers)

        if result.status_code != 200:
            raise AppendrError(result.status_code, result.content + "\n" + new_payload)

    def initialize(self, bin_name, params):
        if 'is_public' in params:
            if params['is_public'] == "true":
                params['is_public'] = True
            elif params['is_public'] == "false":
                params['is_public'] = False

        validate_input_param(params, 'is_public', False, [True, False], False)
        validate_input_param(params, 'api_token', True, validate_non_empty_string, False)
        validate_input_param(params, 'filename', False, validate_non_empty_string, 'data.' + params['output_format'])

        gist_url = "https://api.github.com/gists"

        gist_headers = {
            'Content-Type': 'application/json',
            "Authorization": 'token ' + params['api_token']
        }

        empty_data_string = output_data_formats_empty_string[params['output_format']]

        gist_payload = json.dumps({
            "description" : "Gist created automatically by appendr.appspot.com. Data filename is: " + params['filename'],
            "public" : params['is_public'],
            "files" : {
                params["filename"] : {
                    "content" : empty_data_string
                }
            }
        })

        result = urlfetch.fetch(url=gist_url,
                        payload=gist_payload,
                        method=urlfetch.POST,
                        headers=gist_headers)

        if result.status_code != 201:
            raise AppendrError(result.status_code, "")

        json_content = json.loads(result.content)

        self.is_public = params['is_public']
        self.gist_id = json_content['id']
        self.api_token = params['api_token']
        self.filename = params['filename']

#
# STORAGE BACKENDS
#

storage_backends = {
    'gist' : GistBin
}

#
# OUTPUT FORMATS
#

output_data_formats = ['json', 'csv']
output_data_formats_empty_string = {
    'json' : '[]\n',
    'csv' : 'date_created\n'
}

#
# Bin list format
#

bins_supported_mime_types = ['text/plain', 'application/json']

#
# Accepted data formats
#

bin_supported_mime_types_post = ['application/x-www-form-urlencoded', 'application/json']
bin_data_supported_mime_types_post = ['application/x-www-form-urlencoded', 'application/json']

#
# HANDLERS
#

class BinHandler(webapp2.RequestHandler):
    def options(self):
        self.response.headers.add_header("Access-Control-Allow-Origin", "*")
        self.response.headers.add_header("Access-Control-Allow-Methods", "GET, POST")
        self.response.headers.add_header("Access-Control-Allow-Headers", "Content-Type")
        self.response.headers.add_header("Access-Control-Max-Age", str(60*60*24*30))
        self.response.set_status(200)

    def get(self):
        try:
            self.response.headers.add_header("Access-Control-Allow-Origin", "*")

            accept_header = mimeparse.best_match(bins_supported_mime_types, self.request.headers['Accept'])

            if not accept_header:
                self.error(406)
                return

            api_token = self.request.params.get('api_token', None)

            if 'api_token' is None:
                self.error(400)
                return

            self.response.headers['Content-Type'] = accept_header
            bins = Bin.all().filter("api_token =", api_token).order("-date_created").fetch(None)
            self.response.out.write(serialize_bins(bins, accept_header))
        except AppendrError as e:
            self.response.set_status(e.code)
            self.response.out.write(e.msg)

    def post(self):
        try:
            self.response.headers.add_header("Access-Control-Allow-Origin", "*")
            self.response.headers.add_header("Access-Control-Expose-Headers", "Location")

            content_type = self.request.content_type

            if content_type not in bin_supported_mime_types_post:
                self.error(415)
                return

            params = get_request_params(self.request, content_type)
            bin = Bin.create(params)
            bin.put()

            self.response.headers["Location"] = bin.get_url()
            self.response.set_status(201)
        except AppendrError as e:
            self.response.set_status(e.code)
            self.response.out.write(e.msg)

class DataHandler(webapp2.RequestHandler):
    def options(self, bin_key):
        self.response.headers.add_header("Access-Control-Allow-Origin", "*")
        self.response.headers.add_header("Access-Control-Allow-Methods", "POST")
        self.response.headers.add_header("Access-Control-Allow-Headers", "Content-Type")
        self.response.headers.add_header("Access-Control-Max-Age", str(60*60*24*30))
        self.response.set_status(200)

    def post(self, bin_key):
        try:
            self.response.headers.add_header("Access-Control-Allow-Origin", "*")

            bin_db_key = db.Key.from_path('Bin', bin_key)
            bin = db.get(bin_db_key)

            if (bin is None):
                self.error(404)
                return

            content_type = self.request.content_type

            if content_type not in bin_data_supported_mime_types_post:
                self.error(415)
                return

            params = get_request_params(self.request, content_type)
            params['date_created'] = str(datetime.utcnow())

            queue_name = compute_queue_number_from_bin_id(bin_key, 10)

            taskqueue.add(url='/tasks/append/' + bin_key, queue_name=queue_name, params=params)

            self.response.set_status(204)
        except AppendrError as e:
            self.response.set_status(e.code)
            self.response.out.write(e.msg)

class AppendHandler(webapp2.RequestHandler):
    def post(self, bin_key):
        try:
            bin_db_key = db.Key.from_path('Bin', bin_key)
            bin = db.get(bin_db_key)

            if (bin is None):
                return

            content_type = self.request.content_type

            if content_type not in bin_data_supported_mime_types_post:
                return

            params = get_request_params(self.request, content_type)
            params['date_created'] = dateutil.parser.parse(params['date_created'])

            bin.date_updated = params['date_created']
            bin.append_data(params)
            bin.put()
        except Exception as e:
            return

class CleanupHandler(webapp2.RequestHandler):
    def get(self):
        date_last_update = datetime.utcnow() + dateutil.relativedelta.relativedelta(days = -40)
        unused_bins = Bin.all().order("-date_updated").filter("date_updated <", date_last_update).fetch(None)

        for bin in unused_bins:
            bin.delete()

app = webapp2.WSGIApplication([
    webapp2.Route('/bins', handler=BinHandler),
    webapp2.Route('/bins/<bin_key:\w+>', handler=DataHandler, name="bin"),
    webapp2.Route('/tasks/append/<bin_key:\w+>', handler=AppendHandler),
    webapp2.Route('/tasks/cleanup', handler=CleanupHandler)
], debug=True)
