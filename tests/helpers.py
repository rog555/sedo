import boto3
from boto3.session import Session
import json
import os
from urllib import parse as urlparse
import yaml


def load_file(file):
    if file.endswith('.yaml'):
        return yaml.safe_load(open(file, 'r').read())
    elif file.endswith('.json'):
        return json.loads(open(file, 'r').read())
    else:
        return open(file, 'r').read()


def get_session():
    return Session(region_name=os.environ.get('AWS_REGION', 'us-east-1'))


def get_test_dir(name):
    test_dir = os.path.join(
        os.path.dirname(__file__), 'data', name
    )
    return test_dir


def create_dynamodb_table(table_name, keys=None):
    dynamodb = get_session().resource('dynamodb')
    if not isinstance(keys, list):
        keys = ['tenantId', 'id']
    pt = {
        'ReadCapacityUnits': 1,
        'WriteCapacityUnits': 1
    }
    kwargs = {
        'TableName': table_name,
        'KeySchema': [],
        'AttributeDefinitions': [],
        'ProvisionedThroughput': pt
    }
    attributes = []
    for i, kpair in enumerate(keys):
        if ':' not in kpair:
            kpair += ':S'
        (kname, atype) = kpair.split(':')
        kwargs['KeySchema'].append({
            'AttributeName': kname,
            'KeyType': 'HASH' if i == 0 else 'RANGE'
        })
        attributes.append(kpair)

    for kpair in attributes:
        if ':' not in kpair:
            kpair += ':S'
        (kname, atype) = kpair.split(':')
        kwargs['AttributeDefinitions'].append({
            'AttributeName': kname,
            'AttributeType': atype.upper()
        })
    dynamodb.create_table(**kwargs)
    print('created table %s' % table_name)


def create_queue(queue_name):
    sqs = boto3.client('sqs', region_name='us-east-1')
    account_id = '123456789012'
    dlq_name = queue_name.replace('-queue', '-deadletter-queue')
    dlq_arn = 'arn:aws:sqs:us-east-1:%s:%s' % (account_id, dlq_name)
    sqs.create_queue(QueueName=dlq_name)
    sqs.create_queue(
        QueueName=queue_name,
        Attributes={
            'RedrivePolicy': json.dumps({
                'deadLetterTargetArn': dlq_arn,
                'maxReceiveCount': 3
            })
        }
    )
    print('created queue %s' % queue_name)


def get_queue_url(queue):
    url = get_session().resource('sqs').Queue(queue).url
    # something wrong with moto
    if not url.startswith('https://'):
        url = 'https://queue.amazonaws.com/123456789012/%s' % url
    return url


def get_queue_messages(queue):
    sqs = get_session().client('sqs')
    _messages = sqs.receive_message(
        QueueUrl=get_queue_url(queue),
        MaxNumberOfMessages=10
    ).get('Messages', [])
    messages = []
    for _m in _messages:
        m = json.loads(_m['Body'])
        if (isinstance(m, dict) and m.get('Type') == 'Notification'
           and isinstance(m.get('Message'), str)):
            m = json.loads(json.loads(m['Message'])['default'])
        messages.append(m)
    return messages


def create_infra():
    create_dynamodb_table('sedo_definition')
    create_dynamodb_table('sedo_execution')
    create_queue('sedo_execution-processor-queue')


class invoke(object):
    def __init__(self, handler, method, path, data=None, headers=None):
        _path = urlparse.urlsplit(path).path
        _qs = dict(urlparse.parse_qsl(urlparse.urlsplit(path).query))
        if isinstance(data, dict):
            data = str(json.dumps(data))
        elif isinstance(data, str) and os.path.isfile(data):
            with open(data, 'r') as fh:
                data = fh.read()
        event = {
            'body':                     data,
            'path':                     _path,
            'httpMethod':               method.upper(),
            'queryStringParameters':    _qs,
            'headers': {
                'Host':                 'localhost',
                'X-Forwarded-Proto':    'http',
                'Content-Type':         'application/json'
            }
        }
        if not isinstance(headers, dict):
            headers = {}
        if isinstance(headers, dict):
            event['headers'].update(headers)

        r = handler(event, None)

        self.status_code = int(r.get('statusCode'))
        self.headers = r.get('headers', {})
        self.content = r.get('body')
        try:
            self.json = json.loads(r.get('body'))
        except Exception:
            self.json = {}
