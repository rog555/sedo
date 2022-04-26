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
import json
from moto import mock_dynamodb2
from moto import mock_sqs
import os
import sys
from tests import helpers as h
import time

FUNC_NAME = 'sedo_execution-processor'
ROOT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)))
FUNC_DIR = os.path.join(ROOT_PATH, 'functions', FUNC_NAME)
DATA_PATH = os.path.join(ROOT_PATH, 'tests', 'data', FUNC_NAME)

sys.path.append(FUNC_DIR)
os.chdir(FUNC_DIR)

from processor import get_execution  # noqa: 402
from processor import sqs_handler  # noqa: 402


def _test_file(file):
    return os.path.join(
        h.get_test_dir(FUNC_NAME), file
    )


def get_sqs_event(event):
    return {
        'Records': [{
            'body': json.dumps(event)
        }]
    }


@mock_dynamodb2
@mock_sqs
def test_processor():
    h.create_infra()
    executions = h.load_file(_test_file('execution1.json'))
    h.load_dynamodb_data('sedo_execution', executions)
    event = executions[0].copy()
    execution_id = event['id']
    # print('event %s' % event)
    event.pop('definition', None)
    r = sqs_handler(get_sqs_event(event), None)
    assert r == [
        {
            'id': execution_id,
            'input': {'foo': 'bar'},
            'state': 'ExecutionStarted',
            'tenantId': '123'
        }
    ]

    r = sqs_handler(get_sqs_event(r[0]), None)
    assert r == [
        {
            "id": execution_id,
            "input": {
                "foo": "bar"
            },
            "state": "StepSucceeded",
            "tenantId": "123",
            "step": "wait-some-time"
        }
    ]

    r = sqs_handler(get_sqs_event(r[0]), None)
    # print(json.dumps(r, indent=2))
    wait_time = r[0].pop('wait_timestamp', None)
    assert wait_time.startswith('20')
    assert r == [
        {
            "id": execution_id,
            "input": {
                "foo": "bar"
            },
            "state": "StepStarted",
            "tenantId": "123",
            "step": "wait-some-time"
        }
    ]
    r[0]['wait_timestamp'] = wait_time
    time.sleep(2)

    r = sqs_handler(get_sqs_event(r[0]), None)
    wait_time = r[0].pop('wait_timestamp', None)
    assert r == [
        {
            "id": execution_id,
            "input": {
                "foo": "bar"
            },
            "state": "StepSucceeded",
            "tenantId": "123",
            "step": "last-echo"
        }
    ]

    r = sqs_handler(get_sqs_event(r[0]), None)
    assert r == [
        {
            "id": execution_id,
            "input": {
                "foo": "bar"
            },
            "state": "ExecutionSucceeded",
            "tenantId": "123",
            "step": "last-echo"
        }
    ]

    execution = get_execution('123', execution_id)
    assert execution['state'] == 'ExecutionSucceeded'
