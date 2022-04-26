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
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import Decimal
from boto3.session import Session
from datetime import datetime
import json
from jsonschema import validate
import os
import traceback
from uuid import uuid4


def get_session():
    return Session(region_name=os.environ.get('AWS_REGION', 'us-east-1'))


def get_table(name):
    return get_session().resource('dynamodb').Table(name)


def get_client(name):
    return get_session().client(name)


def problem(title, detail=None, status=400, type=None):
    if isinstance(detail, list):
        detail = {
            'errors': detail
        }
    return {
        'status': status,
        'title': title,
        'detail': detail,
        'type': type
    }, status


def get_exception_object(e):
    return {
        'exception': str(e),
        'stackTrace': traceback.format_tb(e.__traceback__)
    }


def log_exception(title, e):
    exception_object = get_exception_object(e)
    print('EXCEPTION: %s: %s' % (title, exception_object))
    exception_object.pop('stackTrace')
    return problem(title, exception_object, status=500)


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


def query(entity, tenantId, id=None, attributes=None):
    table = get_table(entity)

    def _item(item):
        return json.loads(json.dumps(item, default=json_serial))

    # get by ID
    if tenantId is not None and id is not None:
        response = {}
        try:
            response = get_table(entity).get_item(Key=get_key(tenantId, id))
        except Exception as e:
            return log_exception('unable to get %s' % entity, e)
        if 'Item' not in response:
            return problem(
                '%s not found' % entity.replace('sedo_', ''), status=404
            )
        return _item(response['Item']), 200

    kwargs = {
        'KeyConditionExpression': Key('tenantId').eq(tenantId)
    }

    if isinstance(attributes, list):
        kwargs.update({
            'ProjectionExpression': ', '.join([
                '#%s' % a for a in attributes
            ]),
            'ExpressionAttributeNames': {},
            'Select': 'SPECIFIC_ATTRIBUTES'
        })
    for a in attributes:
        kwargs['ExpressionAttributeNames']['#%s' % a] = a

    response = []
    last_key = None
    try:
        while True:
            if last_key is not None:
                kwargs['ExclusiveStartKey'] = last_key
            r = table.query(**kwargs)
            for item in r['Items']:
                response.append(_item(item))
            if 'LastEvaluatedKey' in r:
                last_key = r['LastEvaluatedKey']
            else:
                break
    except Exception as e:
        return log_exception('unable to query %s' % (entity), e)
    return response, 200


def write(entity, vals, return_vals=None):
    title = 'unable to create %s' % (
        entity
    )
    hk_attr = 'tenantId'
    (hk, rk) = (vals.get(hk_attr), vals.get('id'))
    key = get_key(hk, rk)
    vals.pop(hk_attr, None)
    vals.pop('id', None)
    try:
        table = get_table(entity)
        vals.update(key)
        table.put_item(Item=vals)
        if isinstance(return_vals, list):
            vals = {k: vals[k] for k in return_vals}
        return vals, 201
    except Exception as e:
        return log_exception(title, e)


def delete(entity, vals):
    hk_attr = 'tenantId'
    (hk, rk) = (vals.get(hk_attr), vals.get('id'))
    key = get_key(hk, rk)
    try:
        get_table(entity).delete_item(Key=key)
    except Exception as e:
        return log_exception('unable to delete %s' % entity, e)
    return {
        'message': 'deleted'
    }, 204


def get_definitions(tenantId):
    print('get_definitions(%s)' % tenantId)
    return query('sedo_definition', tenantId, attributes=['tenantId', 'id'])


def create_definition(tenantId, createDefinitionRequest):
    print('create_definition(%s)' % tenantId)
    createDefinitionRequest['tenantId'] = tenantId
    return write(
        'sedo_definition',
        createDefinitionRequest,
        return_vals=['tenantId', 'id']
    )


def get_definition(tenantId, id):
    print('get_definition(%s, %s)' % (tenantId, id))
    return query('sedo_definition', tenantId, id)


def execute_definition(tenantId, id, createExecutionRequest):
    print('execute_definition(%s, %s)' % (tenantId, id))
    # get definition ID
    definition, code = get_definition(tenantId, id)
    if code != 200:
        return (definition, code)
    response = {
        'tenantId': tenantId,
        'id': '%s:%s:%s' % (
            tenantId,
            id,
            str(uuid4()).split('-')[0]
        ),
        'state': 'ExecutionSubmitted'
    }
    event = {
        'input': createExecutionRequest['input']
    }
    event.update(response)

    # validate input
    try:
        validate(event['input'], definition['inputSchema'])
    except Exception as e:
        return problem(
            'input does not pass inputSchema validation', detail=str(e)
        )

    # write to table
    execution_data = event.copy()
    execution_data.update({'definition': definition})
    r, code = write('sedo_execution', execution_data)
    if code != 201:
        return r, code

    # dispatch event to queue
    client = get_client('sqs')
    queue_url = client.get_queue_url(
        QueueName='sedo_execution-processor-queue'
    )['QueueUrl']
    kwargs = {
        'QueueUrl': queue_url,
        'MessageBody': json.dumps(event)
    }
    client.send_message(**kwargs)

    return response, 201


def get_executions(tenantId):
    print('get_executions(%s)' % (tenantId))
    return query(
        'sedo_execution',
        tenantId,
        attributes=['tenantId', 'id', 'state', 'step']
    )


def get_execution(tenantId, id):
    print('get_execution(%s, %s)' % (tenantId, id))
    return query('sedo_execution', tenantId, id)
