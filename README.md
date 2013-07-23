# Appendr

* [Features](README.md#features)
* [Usage](README.md#usage)
* [A note about security](README.md#a-note-about-security)
* [API](README.md#api)
* [Contributing](README.md#contributing)
* [Running your own version on AppEngine](README.md#running-your-own-version-on-AppEngine)
* [Credits](README.md#credits)
* [License](README.md#license)

[Appendr](https://appendr.appspot.com) is a [Google AppEngine](http://appengine.google.com) service that simplifies automated timestamping and collection of key-value data using external services for storing the collected data.
In other words, Appendr is a key-value pair append-only logging utility that uses external services for storage.

For example, a GitHub Gist may be used as an external storage service and after appending 3 key-value pairs two times, the Gist would contain a `data.json` file with this content:

    date_created;key1;key2;key3;key4
    2013-03-04T01-14-43Z;foo1;bar2;baz
    2013-03-04T02-14-43Z;foo2;bar3;baz

or, if you want to store the data in JSON format, the Gist would instead contain a `data.json` file with the same data:

    [
      {
        "date_created" : "2013-03-04T01-14-43Z",
        "key1" : "foo1",
        "key2" : "bar2",
        "key3" : "baz"
      },
      {
        "date_created" : "2013-03-04T02-14-43Z",
        "key1" : "foo2",
        "key2" : "bar3",
        "key3" : "baz"
      }
    ]

Appendr automatically adds the `date_created` timestamp to each key-value dataset it receives.

## Features

Appendr

* **does not store any data** except for the connection to an external storage service. The data you collect is still stored on services that you trust and you can modify that data using those services.

* **simplifies the process of automated data collection** if this process is append-only oriented. Most data storage services have APIs to fetch and modify data, but not to just append data with a single API call. Consequently, you have to do the fetch-modify-store cycle every time you want to append data. Appendr wraps APIs of external storage services in order to provide a simple API for timestamping and appending data.

* **supports distributed data collection** in which concurrent data appends may be happening (i.e. multiple data collectors are sending data to Appendr). Appendr will correctly handle possible race conditions due to the nature of the external storage services' APIs (separate fetch and store API calls).

* **handles external storage service outages** and retries data appends for up to two days. The status of append tasks is always visible to the user.

* **can be invoked cross-domain from a JavaScript script in the browser** since the API supports the [CORS](http://en.wikipedia.org/wiki/Cross-origin_resource_sharing) specification.

* **works with different external storage services**, and currently [GitHub Gist](https://gist.github.com/) and [Dropbox](https://www.dropbox.com/) are supported.

* **accepts key-value data in multiple formats**, and currently JSON (`application/json`) and URL-encoded data (`application/x-www-form-urlencoded`).

* **supports multiple formats for writing received data** to external storage services. Currently, JSON (`application/json`) and CSV (`text/csv`) are supported.

## Usage

Using Appendr involves these steps:

0. **Creating OAuth tokens for external storage services you want to use**. This step must be done by visiting the [Appendr website](https://appendr.appspot.com/#tokens) in your browser, but it should generally be done only once. However, you can create the tokens again if you forget them.

1. **Creating an Appendr bin** by choosing an external storage service and providing an OAuth token for it. You can create as many bins as you want. A bin is a unique link to a specific external storage service - you can think of it as a file which is stored externally, but you have additional permission to write to it via Appendr. Bins can be created either via a form on [Appendr's website](https://appendr.appspot.com/#create) or via [Appendr's API](README.md#create-a-bin). Creating a bin gives you links to raw and HTML versions of the associated data stored on the external storage service used for that bin.

2. **Sending key-value data to a bin**. Appendr automatically timestamps data sent to a bin (as a new key-value pair in the data) and then appends this data to the associated file in the external storage. This step must be done via [Appendr's API](README.md#append-data). You can also use a bin's web page to append some dummy data. Each bin keeps track of the status of data append tasks and exposes these statuses when you query the bin.

3. **Get a list of your bins** stored on a specific external storage service by providing an OAuth token for that service. Again, this can be done either via a form on [Appendr's website](https://appendr.appspot.com/#search) or via [Appendr's API](README.md#search-bins).

Other than creating OAuth tokens, Appendr was developed to be used through its API, as a service called by data-collection processes.

## Example

**See a [demo bin](https://appendr.appspot.com/bins/7A4nk78R280BnImcMw7V)** I have created. This bin uses the GitHub Gist service for storing data, and already has some data appended to it. **View the data** by following the "Content URL (raw)" or "Content URL (html):" links.

**Try appending some dummy data** yourself by clicking the "Append fake data" buttom at the bottom of the screen. Notice that **each time a task is created** and you can track the status of the append task. The task of appending data has completed successfully if its status is "completed".

**View the data** on the external service again to verify that new data has been appended.

## A note about security

Appendr uses a simplified approach to security, which has it's upsides and downsides.

Creating a bin gives you a hard-to-guess bin URL such as this one: `https://appendr.appspot.com/bins/7A4nk78R280BnImcMw7V`. Bin URLs provide [security through obscurity](http://en.wikipedia.org/wiki/Security_through_obscurity) - the URLs are initially known only to you, but you can share them with other people if you want.

Why would you want to share these URLs with other people? Because the URL is linked to your OAuth token which grants permissions of writing data to a file on the external service used for storage. Therefore, knowing the URL means having permissions to append data to that bin, and if you want to enable other people to append data to a specific bin - just give them the URL. This makes collaboration very easy.

What other kinds of permissions are you giving to other people when you give them a bin URL? None. They are only able to write data (in an append-only fashion) to that single bin for which you gave them the URL. They can not modify or delete existing data, nor can they create new bins in your name, nor make any other calls to the external storage service in your name.

If you only want to give other people read-only access to the data stored on the external service - you can give them the URLs for the raw or html content which are available for each bin. For example, this is the URL that enables other people to read the raw data associated with the above bin (Gist-backed bin): `https://gist.github.com/izuzak/09a089eb95641c99a17c/raw/data.json`.

What if someone guesses one of your bin URLs and starts appending garbage to it? Just create another bin and copy your clean data there. Bins are cheap to create. Also, if this starts happening - let me know so that I can increase the length of bin URLs which will make them more unguessable.

## API

* [Create a bin](README.md#create-a-bin)
* [Get a bin](README.md#get-a-bin)
* [Append data](README.md#append-data)
* [Get a task](README.md#get-a-task)
* [Get tasks](README.md#get-tasks)
* [Find bins](README.md#find-tasks)

A few general notes on the API:

1) As the whole application, the API is accessible only via HTTPS.

2) The base path for the API is `https://appendr.appspot.com`. The URLs used in examples below are relative to this base path.

3) Appendr supports CORS so you should be able to call the API from a browser.

4) For POST request, parameters can be specified using two formats: `application/json` and `application/x-www-form-urlencoded`. Examples below use `application/json`, but the same could be done with URL-encoded params in the body. For GET requests, parameters can be specified only using URL-encoded query string parameters.

5) In case an error happens during processing, you will receive a response with a JSON object with the following properties:

* `method` - HTTP method of the request.
* `url` - URL of resource that handled the request.
* `headers` - a JSON object that contains the HTTP headers for the request.
* `body` - the body of the request that was made.
* `response_code` - HTTP response code describing the error.
* `response_title` - HTTP response code title.
* `details` - a human-readable string with a description of the error that happened.
* `stack_trace` - stack trace at the point when the exception was thrown.

Example error response:

    {
      "body": "",
      "stack_trace": "Traceback (most recent call last): ...",
      "url": "https://appendr.appspot.com/bins/somebinidthatdoesntexist",
      "response_code": 404,
      "response_title": "Not Found",
      "headers": {
        "Accept": "*/*",
        "User-Agent": "curl/7.24.0 (x86_64-apple-darwin12.0) libcurl/7.24.0 OpenSSL/0.9.8x zlib/1.2.5",
        "Host": "appendr.appspot.com"
      },
      "details": "The resource could not be found.",
      "method": "GET"
    }

### Create a bin

    POST /bins

Parameters:

* `storage_backend` (optional) - The external service that will be used for data storage.
Possible values: `gist` (GitHub Gist), `dropbox` (Dropbox).
Default value: `gist`.
* `output_format` (optional) - The format in which key-value pairs will be stored in a file of the external storage service.
Possible values: `application/json`, `text/csv`.
Default value: `application/json`.
* `api_token` (mandatory) - The API token that will be used for accessing the external storage service.
* `filename` (optional) - The name of the file (or file-like object) that will created in external storage and contain the data.
Default value: `data.extension`, where the `extension` is determined based on the `output_format`.
E.g. if the output format is `text/csv`, then the default filename will be `data.csv`.
* `is_public` (optional, `gist` storage backend only) - Defines if the Gist will be created as a public Gist.
Possible values: `true`, `false`.
Default value: `false`.

The response will contain a `Location` header with the Appendr URL of the bin to which data should be sent, and a representation of that bin:

    201 Created
    Location: https://appendr.appspot.com/bins/:bin_id
    Content-type: application/json

    {
      ...
    }

Example request:

    POST /bins
    Content-Type: application/json
    Accept: application/json

    {
      "storage_backend" : "gist",
      "output_format" : "json",
      "is_public" : false,
      "api_token" : "1234567890abcdefg",
      "filename" : "my_data.json"
    }

Example response (after creating a Gist with a file named `my_data.json`):

    201 Created
    Location: https://appendr.appspot.com/bins/123abc456def789ghi00
    Content-type: application/json

    {
      "bin_id": "123abc456def789ghi00",
      "bin_url": "https://appendr.appspot.com/bins/123abc456def789ghi00",
      "storage_backend": "gist",
      "output_format": "application/json",
      "filename": "data.json",
      "is_public": false,
      "date_updated": "2013-07-17T08:38:43Z",
      "date_created": "2013-07-17T08:38:40Z",
      "datetime_format": "%Y-%m-%dT%H:%M:%SZ",
      "content_raw_url": "https://gist.github.com/raw/somegistid/data.json",
      "content_html_url": "https://gist.github.com/somegistid",
      "gist_id": "somegistid",
      "gist_api_url": "https://api.github.com/gists/somegistid",
      "tasks_url": "https://appendr.appspot.com/bins/123abc456def789ghi00/tasks",
      "tasks": []
    }

See [Get a bin](README.md#get-a-bin) section below for an explanation of the properties of the returned JSON object.

When a bin is created, a file (or file-like object) is also created on the selected external storage service to hold the data for the bin. This file will have some initial bytes depending on the selected output format.

### Get a bin

    GET /bins/:bin_id

The response will contain a JSON object with the following properties:

* `bin_id` - the Appendr ID for this bin.
* `bin_url` - full URL for this bin.
* `storage_backend` - storage backend service that this bin uses.
* `output_format` - MIME type of serialization format used for writing data to external storage service.
* `filename` - name of file that stores the data on the external storage service.
* `is_public` - (`gist` backend only) whether or not the gist storing the data was created as a public gist.
* `date_created` - date and time of bin creation.
* `date_updated` - date and time of last successful data append task, or date and time of bin creation of no data has been appended yet.
* `datetime_format` - format used for `date_updated` and `date_created`.
* `content_raw_url` - link to the content-only version of the data associated with this bin on the external storage service.
* `content_html_url` - link to a human-friendly web page version of the data associated with this bin on the external storage service.
* `gist_id` - (`gist` backend only) the GitHub id for the gist that stores the data for this bin.
* `gist_api_url` - (`gist` backend only) link to the [GitHub API resource that describes the gist that stores the data](http://developer.github.com/v3/gists/#get-a-single-gist).
* `tasks_url` - link to the resource that lists recent task objects. See [Get tasks](README.md#get-tasks).
* `tasks` - an array of recent task objects for this bin. See [Get a task](README.md#get-a-task) for an explanation of the properties of task objects.

Example request:

    GET /bins/123abc456def789ghi00
    Accept: application/json

Example response:

    200 OK
    Content-type: application/json

    {
      "bin_id": "123abc456def789ghi00",
      "bin_url": "https://appendr.appspot.com/bins/123abc456def789ghi00",
      "storage_backend": "gist",
      "output_format": "application/json",
      "filename": "data.json",
      "is_public": false,
      "date_updated": "2013-07-17T08:38:43Z",
      "date_created": "2013-07-17T08:38:40Z",
      "datetime_format": "%Y-%m-%dT%H:%M:%SZ",
      "content_raw_url": "https://gist.github.com/raw/somegistid/data.json",
      "content_html_url": "https://gist.github.com/somegistid",
      "gist_id": "somegistid",
      "gist_api_url": "https://api.github.com/gists/somegistid",
      "tasks_url": "https://appendr.appspot.com/bins/123abc456def789ghi00/tasks",
      "tasks": []
    }

### Append data

    POST https://appendr.appspot.com/bins/:bin_id

Parameters:

* set of key-value pairs that will be timestamped and appended to the existing data

The response will contain a `Location` header with the Appendr URL of the task that is responsible for appending the new data to the existing data, and a representation of that task in the body:

    202 Accepted
    Location: https://appendr.appspot.com/bins/:bin_id/tasks/:task_id
    Content-type: application/json

    {
      ...
    }

Example request:

    POST /bins/123abc456def789ghi00
    Content-Type: application/json
    Accept: application/json

    {
      "key1" : "foo1",
      "key2" : "bar2",
      "key3" : "baz"
    }

Example response:

    202 Accepted
    Content-Type: application/json
    Location: https://appendr.appspot.com/bins/123abc456def789ghi00/tasks/foobarbazboom

    {
      "task_id": "0gdWop8iVTMxx2Hd0ipc",
      "task_url": "https://appendr.appspot.com/bins/7A4nk78R280BnImcMw7V/tasks/0gdWop8iVTMxx2Hd0ipc",
      "tasks_url": "https://appendr.appspot.com/bins/7A4nk78R280BnImcMw7V/tasks",
      "status": "completed",
      "status_msg": "",
      "date_created": "2013-07-23T08:39:09Z",
      "date_updated": "2013-07-23T08:39:10Z",
      "datetime_format": "%Y-%m-%dT%H:%M:%SZ",
      "bin_url": "https://appendr.appspot.com/bins/7A4nk78R280BnImcMw7V",
      "bin_id": "7A4nk78R280BnImcMw7V"
    }

See [Get a task](README.md#get-a-task) section below for an explanation of the properties of the returned JSON object.

### Get a task

    GET /bins/:bin_id/tasks/:task_id

The response will contain a JSON object with the following properties:

* `task_id` - the Appendr ID for this task.
* `task_url` - full URL for this task.
* `tasks_url` - full URL for the list of all task for the bin that this task is associated with.
* `status` - task status. One of: `queued` (task not executed yet), `completed` (data successfully appended), `retrying` (append failed and will retry in some time), `failed` (append failed and will not be retried any more).
* `status_msg` - a string that describes the last error if `status` is `failed` or `retrying`.
* `date_created` - date and time of task creation.
* `date_updated` - date and time of last attempt to append the new data to external storage.
* `datetime_format` - format used for `date_updated` and `date_created`.
* `bin_url` - full URL for the bin that this task is associated with.
* `bin_id` - the Appendr ID for the bin that this task is associated with.

Example request:

    GET /bins/123abc456def789ghi00/tasks/foobarbazboom
    Accept: application/json

Example response:

    200 OK
    Content-type: application/json

    {
      "task_id": "0gdWop8iVTMxx2Hd0ipc",
      "task_url": "https://appendr.appspot.com/bins/7A4nk78R280BnImcMw7V/tasks/0gdWop8iVTMxx2Hd0ipc",
      "tasks_url": "https://appendr.appspot.com/bins/7A4nk78R280BnImcMw7V/tasks",
      "status": "completed",
      "date_created": "2013-07-23T08:39:09Z",
      "date_updated": "2013-07-23T08:39:10Z",
      "datetime_format": "%Y-%m-%dT%H:%M:%SZ",
      "status_msg": "",
      "bin_url": "https://appendr.appspot.com/bins/7A4nk78R280BnImcMw7V",
      "bin_id": "7A4nk78R280BnImcMw7V"
    }

### Get tasks

    GET /bins/:bin_id/tasks

The response will contain a JSON array of task objects.

Example request:

    GET /bins/123abc456def789ghi00/tasks
    Accept: application/json

Example response:

    200 OK
    Content-type: application/json

    [
      {
        "task_id": "0gdWop8iVTMxx2Hd0ipc",
        "task_url": "https://appendr.appspot.com/bins/7A4nk78R280BnImcMw7V/tasks/0gdWop8iVTMxx2Hd0ipc",
        "tasks_url": "https://appendr.appspot.com/bins/7A4nk78R280BnImcMw7V/tasks",
        "status": "completed",
        "date_created": "2013-07-23T08:39:09Z",
        "date_updated": "2013-07-23T08:39:10Z",
        "datetime_format": "%Y-%m-%dT%H:%M:%SZ",
        "status_msg": "",
        "bin_url": "https://appendr.appspot.com/bins/7A4nk78R280BnImcMw7V",
        "bin_id": "7A4nk78R280BnImcMw7V"
      }
    ]

### Find bins

    GET /bins

Parameters:

* `storage_backend` (mandatory) - The external service for which you want to find your bins.
Possible values: `gist` (GitHub Gist), `dropbox` (Dropbox).
* `api_token` (mandatory) - The API token that will be used for accessing the external storage service. This doesn't have to be exactly the same token used for creating the bins, it just has to be a valid token for your account on the external service.

The response will contain an array of bin objects that match the criteria.

Example request:

    GET /bins?storage_backend=gist&api_token=1234567890abcdefg
    Accept: application/json

Example response:

    200 OK
    Content-type: application/json

    [
      {
        "bin_id": "123abc456def789ghi00",
        "bin_url": "https://appendr.appspot.com/bins/123abc456def789ghi00",
        "storage_backend": "gist",
        "output_format": "application/json",
        "filename": "data.json",
        "is_public": false,
        "date_updated": "2013-07-17T08:38:43Z",
        "date_created": "2013-07-17T08:38:40Z",
        "datetime_format": "%Y-%m-%dT%H:%M:%SZ",
        "content_raw_url": "https://gist.github.com/raw/somegistid/data.json",
        "content_html_url": "https://gist.github.com/somegistid",
        "gist_id": "somegistid",
        "gist_api_url": "https://api.github.com/gists/somegistid",
        "tasks_url": "https://appendr.appspot.com/bins/123abc456def789ghi00/tasks",
        "tasks": []
      }
    ]

## Contributing

Pull requests are welcome! Please see [these notes](CONTRIBUTING.md).

## Running your own version on AppEngine

1) Create an AppEngine account and [create a new AppEngine app](https://appengine.google.com/) with some name.
2) Clone this repo locally: `git clone https://github.com/izuzak/appendr`
3) Edit `app.yaml` and change `application: appendr` to `application: APPENGINE_APP_NAME_FROM_STEP_1`
4) Create OAuth applications on services for backend storage (so that Appendr can use their APIs).

  * To create a GitHub application, go [here](https://github.com/settings/applications/new). For the homepage URL put down: `https://APPENGINE_APP_NAME_FROM_STEP_1.appspot.com`, and for callback URL put down: `https://APPENGINE_APP_NAME_FROM_STEP_1.appspot.com/oauth_token_github`. Put anything you like for Application name. After creating the application, write down the Application's Client ID and Client Secret.
  * To create a Dropbox application, go [here](https://www.dropbox.com/developers/apps/create) and choose Dropbox API app. "What type of data does your app need to store on Dropbox?" --> Files and datastores. "Can your app be limited to its own, private folder?" --> Yes. Put anything you like for Application name. In the setting, enable additional users and for redirect URL put down: `https://APPENGINE_APP_NAME_FROM_STEP_1.appspot.com/oauth_token_dropbox`. Also, write down the Application's App key and App Secret.

5) Create a file named `appendr_cfg.py` in the root directory of the cloned repo, with the following contents:

```github_client_id = 'CLIENT_ID_FOR_GITHUB_APP'
github_client_secret = 'CLIENT_SECRET_FOR_GITHUB_APP'
dropbox_client_id = 'APP_KEY_FOR_DROPBOX_APP'
dropbox_client_secret = 'APP_SECRET_FOR_DROPBOX_APP'
```

Of course, these IDs and secrets are the ones you got from the previous step after creating GitHub/Dropbox apps.

6) Upload your application to AppEngine and verify that `https://APPENGINE_APP_NAME_FROM_STEP_1.appspot.com` works.

## Credits

Appendr is built with many awesome open-source projects:
* [mimeparse](https://code.google.com/p/mimeparse/)
* [dateutil](http://labix.org/python-dateutil)
* [Jinja2](http://jinja.pocoo.org/docs/)
* [Bootstrap](http://twitter.github.io/bootstrap/index.html)
* [JQuery](http://jquery.com/)

## License

Created by [Ivan Zuzak](http://ivanzuzak.info). Licensed under the [Apache 2.0 License](https://github.com/izuzak/appendr/blob/master/LICENSE.md).
[![gaugestracking alpha](https://secure.gaug.es/track.gif?h[site_id]=51a24cc5613f5d2a14000044&h[resource]=http%3A%2F%2Fgithub.com%2Fizuzak%2Fappendr&h[title]=appendr%20%28GitHub%29&h[unique]=1&h[unique_hour]=1&h[unique_day]=1&h[unique_month]=1&h[unique_year]=1 "ivanzuzak.info")](http://ivanzuzak.info/)
