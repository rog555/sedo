#!/usr/bin/env python
import boto3
import json
from jsonschema import validate
import traceback
from uuid import uuid4


def get_table(name):
    return boto3.resource('dynamodb').Table(name)


def get_client(name):
    return boto3.client(name)


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


def query(entity, tenantId, id=None):
    table = get_table(entity)

    def _item(item):
        return json.loads(json.dumps(item))

    # get by ID
    if tenantId is not None and id is not None:
        response = {}
        try:
            response = get_table(entity).get_item(Key=get_key(tenantId, id))
        except Exception as e:
            return log_exception('unable to get %s' % entity, e)
        if 'Item' not in response:
            return problem('%s not found' % entity, status=404)
        return _item(response['Item']), 200

    # query
    kwargs = {}
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


def write(entity, vals, update=False):
    title = 'unable to %s %s' % (
        'update' if update is True else 'create',
        entity
    )
    hk_attr = 'tenantId'
    (hk, rk) = (vals.get(hk_attr), vals.get('id'))
    key = get_key(hk, rk)
    vals.pop(hk_attr, None)
    vals.pop('id', None)
    try:
        table = get_table(entity)
        if update is True:
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
                response = table.update_item(**kwargs)
                vals.update(response.get('Attributes'))
        else:
            vals.update(key)
            table.put_item(Item=vals)
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
    return query('sedo_definitions', tenantId)


def create_definition(tenantId, createDefinitionRequest):
    print('create_definition(%s)' % tenantId)
    return write('sedo_execution', {
        'tenantId': tenantId
    }.update(createDefinitionRequest))


def get_definition(tenantId, id):
    print('get_definition(%s, %s)' % (tenantId, id))
    return query('sedo_definitions', tenantId, id)


def execute_definition(tenantId, id, createExecutionRequest):
    print('execute_definition(%s, %s)' % (tenantId, id))
    # get definition ID
    definition, code = get_definition(tenantId, id)
    if code != 200:
        return (definition, code)
    response = {
        'tenantId': tenantId,
        'definitionId': id,
        'id': str(uuid4()).split('-')[0],
        'state': 'ExecutionSubmitted'
    }
    event = {
        'input': createExecutionRequest['input'],
        'definition': definition
    }.update(response)

    # validate input
    try:
        validate(event['input'], definition['inputSchema'])
    except Exception as e:
        return problem(
            'input does not pass inputSchema validation', detail=str(e)
        )

    # write to table
    write('sedo_execution', event)

    # dispatch to queue
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
    return query('sedo_executions', tenantId)


def get_execution(tenantId, id):
    print('get_execution(%s, %s)' % (tenantId, id))
    return query('sedo_executions', tenantId, id)