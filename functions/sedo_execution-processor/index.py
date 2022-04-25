#!/usr/bin/env python
import argparse
import boto3
from datetime import datetime
from datetime import timedelta
import dateutil
import json
from jsonschema import validate
from uuid import uuid4
import yaml


EVENT_SCHEMA = yaml.safe_load('''
type: object
properties:
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
  id:
    type: string
  definition:
    id:
      type: string
      pattern: '^[a-z-]+$'
    inputSchema:
      type: object
    steps:
      type: array
      items:
        type: object
        properties:
          id:
            type: string
            pattern: '^[a-z-]+$'
          type:
            type: string
            enum:
              - wait
              - echo
          next:
            type: string
            pattern: '^[a-z-]+$'
          end:
            type: boolean
          seconds:
            type: number
            minimum: 10
          message:
            type: string
        additionalProperties: false
        required:
          - id
          - type
    required:
      - id
      - inputSchema
      - steps
    additionalProperties: false
  step:
    type: string
    pattern: '^[a-z-]+$'
  wait_timestamp:
    type: string
  stash:
    type: object
required:
  - state
  - definition
additionalProperties: false
''')


def add_utc_tz(x):
    return x.replace(tzinfo=dateutil.tz.gettz("UTC"))


def now_dt():
    return add_utc_tz(datetime.utcnow())


def timestamp(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def handler(event, context):
    # handle either sqs or invoke events
    if 'Records' in event:
        return sqs_handler(event)
    elif 'state' in event:
        try:
            return process_event(event)
        except Exception as e:
            raise Exception('exception processing event %s: %s' % (event, e))
    else:
        raise Exception('event %s not supported' % event)


def sqs_handler(event):
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
    return {
        'responses': responses
    }


def dispatch_event(event, wait_seconds=None):
    print('dispatch_event() %s, wait_seconds=%s' % (event, wait_seconds))
    return
    client = boto3.client('sqs')
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
    if event['state'] == 'ExecutionSubmitted':
        event['id'] = str(uuid4()).split('-')[0]
        event['state'] = 'ExecutionStarted'

    elif event['state'] in [
        'ExecutionStarted', 'StepStarted', 'StepSucceeded'
    ]:
        event['state'] = 'StepStarted'

        # get first step if not defined otherwise current step
        current_step = event.get('step')
        sd = None
        for _sd in event['steps']:
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
                print('wait_seconds %s' % wait_seconds)
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

    if event['state'] not in ['ExecutionSucceeded', 'ExecutionFailed']:
        dispatch_event(event, wait_seconds=wait_seconds)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description='Serveless Event Driven Orchestrator'
    )
    ap.add_argument('definition', help='definition yaml file')
    ap.add_argument('state', choices=[
        'ExecutionSubmitted',
        'ExecutionStarted',
        'StepStarted',
        'StepSucceeded'
    ])
    ap.add_argument('--step', help='current step')
    ap.add_argument('--wait', help='wait timestamp')
    args = ap.parse_args()
    event = {
        'state': args.state,
        'definition': yaml.safe_load(open(args.definition, 'r').read())
    }
    if args.step is not None:
        event['step'] = args.step
    if args.wait is not None:
        event['wait_timestamp'] = args.wait

    response = handler(event, None)
    print(json.dumps(response, indent=2))
