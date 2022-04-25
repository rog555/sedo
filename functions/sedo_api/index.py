#!/usr/bin/env python
import awsgi
import connexion
import json
from flask_cors import CORS
from traceback import print_exc

global APP
APP = None


def handler(event, context):
    global APP
    try:
        if APP is None:
            APP = connexion.FlaskApp(__name__)
            APP.add_api('api.yaml')
            CORS(APP.app)
        return awsgi.response(APP, event, context)
    except Exception as e:
        print_exc()
        return {
            'statusCode': 500,
            'body': json.dumps({
                'title': 'Internal Server Error',
                'detail': 'execution invoking API: %s' % str(e),
                'status': 500,
                'type': None
            }),
            'headers': {
                'Content-Type': 'application/json',
            }
        }