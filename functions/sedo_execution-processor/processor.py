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
from boto3.dynamodb.types import Decimal
from boto3.session import Session
from datetime import datetime
from datetime import timedelta
import dateutil
import json
from jsonschema import validate
import os
import traceback
import yaml


EVENT_SCHEMA = yaml.safe_load('''
type: object
properties:
  tenantId:
    type: string
    pattern: '^[a-z0-9-]+$'
  id:
    type: string
    pattern: '^[a-z0-9:-]+$'
  state:
    type: string
    enum:
      - ExecutionSubmitted
      - ExecutionStarted
      - StepStarted
      - StepFailed
      - StepSucceeded
      - ExecutionSucceeded
      - ExecutionFailed
  input:
    type: object
  step:
    type: string
    pattern: '^[a-z-]+$'
  wait_timestamp:
    type: string
  stash:
    type: object
required:
  - tenantId
  - id
  - state
additionalProperties: false
''')


def add_utc_tz(x):
    return x.replace(tzinfo=dateutil.tz.gettz("UTC"))


def now_dt():
    return add_utc_tz(datetime.utcnow())


def timestamp(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def get_session():
    return Session(region_name=os.environ.get('AWS_REGION', 'us-east-1'))


def get_table(name):
    return get_session().resource('dynamodb').Table(name)


def get_client(name):
    return get_session().client(name)


def get_key(tenantId, id):
    return {
        'tenantId': tenantId,
        'id': id
    }


def json_serial(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        if obj % 1 > 0:
            return float(obj)
        else:
            return int(obj)
    if isinstance(obj, set):
        return list(obj)
    raise TypeError('type not serializable')


def get_exception_object(e):
    return {
        'exception': str(e),
        'stackTrace': traceback.format_tb(e.__traceback__)
    }


def log_exception(title, e):
    exception_object = get_exception_object(e)
    print('EXCEPTION: %s: %s' % (title, exception_object))
    raise Exception(e)


def get_execution(tenant_id, id):
    r = get_table('sedo_execution').get_item(Key=get_key(tenant_id, id))
    if 'Item' not in r:
        raise Exception('execution not found')
    return json.loads(json.dumps(r['Item'], default=json_serial))


def update_execution(execution, vals):
    title = 'unable to update execution'
    key = get_key(execution['tenantId'], execution['id'])
    try:
        table = get_table('sedo_execution')
        kwargs = {
            'Key': key,
            'ReturnValues': 'ALL_NEW'
        }
        exp = []
        _vals = {}
        aliases = {}
        for k, v in vals.items():
            if isinstance(v, str) and v == '':
                v = None
            aliases['#%s' % k] = k
            if isinstance(v, list):
                exp.append('#%s = list_append(#%s, :%s)' % (k, k, k))
                _vals[':%s' % k] = v
            else:
                exp.append('#%s = :%s' % (k, k))
                _vals[':%s' % k] = v
        if len(_vals):
            kwargs['ExpressionAttributeValues'] = _vals
            kwargs['UpdateExpression'] = 'SET %s' % ', '.join(exp)
        if len(aliases):
            kwargs['ExpressionAttributeNames'] = aliases
            table.update_item(**kwargs)
    except Exception as e:
        log_exception(title, e)


def dispatch_event(event, wait_seconds=None):
    print('dispatch_event() %s, wait_seconds=%s' % (event, wait_seconds))
    client = get_session().client('sqs')
    queue_url = client.get_queue_url(
        QueueName='sedo_execution-processor-queue'
    )['QueueUrl']
    kwargs = {
        'QueueUrl': queue_url,
        'MessageBody': json.dumps(event)
    }
    if wait_seconds is not None:
        if wait_seconds < 0:
            wait_seconds = 0
        elif wait_seconds > 300:
            wait_seconds = 300
        kwargs['DelaySeconds'] = wait_seconds
    client.send_message(**kwargs)


def process_event(event):
    validate(event, EVENT_SCHEMA)
    wait_seconds = None
    print('process_event(): %s' % event)

    # get execution to check its valid/exists
    execution = get_execution(event['tenantId'], event['id'])
    output = None

    if event['state'] == 'ExecutionSubmitted':
        event['state'] = 'ExecutionStarted'

    elif event['state'] in [
        'ExecutionStarted', 'StepStarted', 'StepSucceeded'
    ]:
        event['state'] = 'StepStarted'
        if execution['state'] != event['state']:
            update_execution(execution, {'state': event['state']})

        # get first step if not defined otherwise current step
        current_step = event.get('step')
        sd = None
        for _sd in execution['definition']['steps']:
            sd = _sd
            if current_step is None:
                current_step = _sd['id']
                break
            elif current_step == _sd['id']:
                break

        # echo step
        if sd['type'] == 'echo':
            print('STEP %s ECHO: %s' % (
                current_step, sd.get('message', 'some message'))
            )
            event['state'] = 'StepSucceeded'

        # wait step
        elif sd['type'] == 'wait':
            wait_seconds = 0
            if 'wait_timestamp' not in event:
                # initial wait seconds
                wait_seconds = int(sd.get('seconds', 10))
                event['wait_timestamp'] = timestamp(
                    now_dt() + timedelta(seconds=wait_seconds)
                )
            else:
                # remaining wait seconds
                wait_dt = add_utc_tz(
                    dateutil.parser.parse(event['wait_timestamp'])
                )
                wait_seconds = int((wait_dt - now_dt()).total_seconds())
            if wait_seconds <= 0:
                wait_seconds = None
                event.pop('wait_timestamp', None)
                event['state'] = 'StepSucceeded'
            if 'wait_timestamp' in event:
                print('STEP %s WAIT: %s seconds until %s' % (
                    current_step, wait_seconds, event['wait_timestamp']
                ))

        if event['state'] == 'StepSucceeded':
            if sd.get('end') is True:
                event['state'] = 'ExecutionSucceeded'
            elif 'next' in sd:
                event['step'] = sd['next']

    execution_update = {'state': event['state']}
    if 'step' in event:
        execution_update['step'] = event['step']
    if output is not None:
        event['input'] = output
        execution_update['output'] = output
    update_execution(execution, execution_update)

    if event['state'] not in ['ExecutionSucceeded', 'ExecutionFailed']:
        dispatch_event(event, wait_seconds=wait_seconds)
    return event


def sqs_handler(event, context):
    records = event['Records']
    responses = []
    for record in records:
        msg = None
        event = json.loads(record['body'])
        try:
            msg = process_event(event)
        except Exception as e:
            msg = 'exception processing event %s: %s' % (event, e)
        print(msg)
        responses.append(msg)
    return responses
