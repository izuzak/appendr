# Appendr

* [Features](README.md#features)
* [API](README.md#api)
* [Credits](README.md#credits)
* [License](README.md#license)

Appendr is a [Google AppEngine](http://appengine.google.com) service for appending timestamped key-value pairs to external storage services.
In other words, Appendr is a key-value pair append-only logging utility that uses external services for storage.

Appendr itself does not store any data except for the link to an external storage service.
It just wraps the external storage services in order to provide a simple API for timestamping and appending data, which most external services do not provide.

For example, a GitHub Gist may be used as an external storage service and after creating an Appendr "bin" and sending it 3 key-value pairs two times, the Gist would contain a `data.csv` file with this content:

    date_created;key1;key2;key3;key4
    2013-03-04T01-14-43Z;foo1;bar2;baz
    2013-03-04T02-14-43Z;foo2;bar3;baz

If the JSON format was chosen while creating an Appendr "bin", the Gist would insted contain a `data.json` file with the same data:

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

[CORS](http://en.wikipedia.org/wiki/Cross-origin_resource_sharing) support
* Appendr may be called cross-domain from a JavaScript script in a browser

Supported external storage services:
* [GitHub Gist](https://gist.github.com/)

Supported input formats:
* `application/json`
* `application/x-www-form-urlencoded`

Supported output formats:
* `application/json`
* `text/csv`

## API

Using Appendr consists of two steps:
1. creating an Appendr "bin" linking it to an external storage service
2. sending key-value pairs to the created bin and Appendr timestamps and appends this data to a file in the external storage

### Create an Appendr bin

To create an bin that will serve as an endpoint for appending data to an external service:

    POST https://appendr.appspot.com/bins

Parameters for any external storage service used:

* `storage_backend` (optional) - The external service that will be used for data storage.
Possible values: `gist` (GitHub Gist).
Default value: `gist`.
* `output_format` (optional) - The format in which key-value pairs will be stored in a file of the external storage service.
Possible values: `json`, `csv`.
Default value: `json`.
* `datetime_format` (optional) - The format in which data timestamps will be written.
Default value: `%Y-%m-%dT%H:%M:%SZ`

Additional parameters for using Gists for external storage:

* `is_public` (optional) - Defines if the Gist will be created as a public Gist.
Possible values: `true`, `false`.
Default value: `false`.
* `api_token` (mandatory) - The GitHub API token that will be used for creating Gists.
* `filename` (optional) - The name of the file in the Gist that will created and contain the data.
Default value: `data.extension`, where the `extension` is determined based on the `output_format`.
E.g. if the output format is `csv`, then the default filename will be `data.csv`.

Parameters should be passed in the request body as key-value pairs formatted either in JSON (`application/json`) or url-encoded format (`application/x-www-form-urlencoded`).

The response will contain a `Location` header with the Appendr URL representing the "bin" to which data should be sent:

    201 Created
    Location: https://appendr.appspot.com/bins/:bin_id

Example request:

    POST https://appendr.appspot.com/bins
    Content-Type: application/json

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

### Send data to Appendr bin

To append data to a file stored in an external service:

    POST https://appendr.appspot.com/bins/:bin_id

with the body containing key-value pairs in one of the following formats:
* application/json
* text/csv

Example request:

    POST https://appendr.appspot.com/bins/123abc456def789ghi00
    Content-Type: application/json

    {
      "key1" : "foo1",
      "key2" : "bar2",
      "key3" : "baz"
    }

Example response (after appending data to the file in a Gist):

    204 OK

After which the file `my_data.json` in the created Gist will look like this:

    [
      {
        "date_created" : "2013-03-04T01-14-43Z",
        "key1" : "foo1",
        "key2" : "bar2",
        "key3" : "baz"
      }
    ]

## Credits

Noam is built with many awesome open-source projects:
* [mimeparse](https://code.google.com/p/mimeparse/)

## License

Created by [Ivan Zuzak](http://ivanzuzak.info).
Licensed under the [Apache 2.0 License](https://github.com/izuzak/appendr/blob/master/LICENSE.md).

[![gaugestracking alpha](https://secure.gaug.es/track.gif?h[site_id]=51a24cc5613f5d2a14000044&h[resource]=http%3A%2F%2Fgithub.com%2Fizuzak%2Fappendr&h[title]=appendr%20%28GitHub%29&h[unique]=1&h[unique_hour]=1&h[unique_day]=1&h[unique_month]=1&h[unique_year]=1 "ivanzuzak.info")](http://ivanzuzak.info/)
