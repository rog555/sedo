#!/usr/bin/env python
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import awsgi
import connexion
from flask_cors import CORS
import json
from traceback import print_exc

global APP
APP = None


def handler(event, context):
    global APP
    try:
        if APP is None:
            APP = connexion.FlaskApp(__name__, options={'swagger_ui': False})
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
