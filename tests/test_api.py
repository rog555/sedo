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
from moto import mock_dynamodb2
from moto import mock_sqs
import os
import sys
from tests import helpers as h

BASE_PATH = '/sedo/tenants/123'
FUNC_NAME = 'sedo_api'
ROOT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)))
FUNC_DIR = os.path.join(ROOT_PATH, 'functions', FUNC_NAME)
DATA_PATH = os.path.join(ROOT_PATH, 'tests', 'data', FUNC_NAME)

sys.path.append(FUNC_DIR)
os.chdir(FUNC_DIR)

from index import handler  # noqa: 402


def _test_file(file):
    return os.path.join(
        h.get_test_dir(FUNC_NAME), file
    )


@mock_dynamodb2
@mock_sqs
def test_definition_api():
    h.create_infra()

    # check no definitions
    r = h.invoke(handler, 'GET', BASE_PATH + '/definitions')
    assert r.json == []

    # create definition
    data = h.load_file(_test_file('definition1.yaml'))
    r = h.invoke(handler, 'POST', BASE_PATH + '/definitions', data)

    assert r.json == {'id': 'definition1', 'tenantId': '123'}

    # get definitions
    r = h.invoke(handler, 'GET', BASE_PATH + '/definitions')
    assert r.json == [{'id': 'definition1', 'tenantId': '123'}]

    # get definition
    data['tenantId'] = '123'
    r = h.invoke(handler, 'GET', BASE_PATH + '/definitions/definition1')
    assert r.json == data


@mock_dynamodb2
@mock_sqs
def test_execution_api():
    h.create_infra()

    # create definition
    definition = h.load_file(_test_file('definition1.yaml'))
    r = h.invoke(handler, 'POST', BASE_PATH + '/definitions', definition)

    # create invalid execution (definition not found)
    data = {'input': {'bar': 'baz'}}
    r = h.invoke(
        handler,
        'POST',
        BASE_PATH + '/definitions/invalid/execute',
        data=data
    )
    assert r.json == {
        'detail': None,
        'status': 404,
        'title': 'definition not found',
        'type': None
    }

    # create invalid execution
    r = h.invoke(
        handler,
        'POST',
        BASE_PATH + '/definitions/definition1/execute',
        data=data
    )
    assert r.json['status'] == 400
    assert r.json['title'] == 'input does not pass inputSchema validation'
    assert r.json['detail'].startswith("'foo' is a required property")

    # check no executions
    r = h.invoke(
        handler,
        'GET',
        BASE_PATH + '/executions'
    )
    assert r.json == []

    # create valid execution
    data = {'input': {'foo': 'bar'}}
    r = h.invoke(
        handler,
        'POST',
        BASE_PATH + '/definitions/definition1/execute',
        data=data
    )
    execution_id = r.json['id']
    assert execution_id.startswith('123:definition1:')
    assert len(execution_id) == len('123:definition1:12345678')
    assert r.json['state'] == 'ExecutionSubmitted'
    assert r.json['tenantId'] == '123'

    # check executions table
    r = h.invoke(
        handler,
        'GET',
        BASE_PATH + '/executions'
    )
    assert r.json == [{
        'tenantId': '123',
        'id': execution_id,
        'state': 'ExecutionSubmitted'
    }]

    # get specific execution
    print('getting execution')
    r = h.invoke(
        handler,
        'GET',
        BASE_PATH + '/executions/' + execution_id
    )
    definition['tenantId'] = '123'
    expected = {
        "input": {
            "foo": "bar"
        },
        "state": "ExecutionSubmitted",
        "tenantId": "123",
        "id": execution_id,
        'definition': definition
    }
    assert r.json == expected

    # check dispatched messages on queue
    expected.pop('definition', None)
    events = h.get_queue_messages('sedo_execution-processor-queue')
    assert events == [expected]
