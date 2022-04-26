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
import argparse
import json
import yaml

from processor import sqs_handler


def handler(event, context):
    return sqs_handler(event, context)


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

    response = handler({
        'Records': [{
            'body': json.dumps(event)
        }]
    }, None)
    print(json.dumps(response, indent=2))
