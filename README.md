# sedo
**S**erverless **E**vent **D**riven **O**rchestrator

The purpose of sedo is to demonstrate how an event driven orchestrator using only AWS Lambda, SQS and DynamoDB would work

It is **NOT** intended to be used in production, though a similar approach has been used at scale in production

## Example Definition

```
id: example-definition

inputSchema:
  type: object
  properties:
    foo:
      type: string
  required: [foo]
  additionalProperties: false

steps:
  - id: initial-echo
    type: echo
    message: initial echo
    next: wait-some-time

  - id: wait-some-time
    type: wait
    seconds: 45
    next: last-echo

  - id: last-echo
    type: echo
    message: last echo
    end: true
```

## Architecture ##

sedo differs to AWS Step Function in that only AWS Lambda and SQS are used to asynchronously orchestrate workflows.  Although Step Functions is invoked aysnchronously, it internally executes and monitors state machines synchronously in order to handle errors.  

Some of the design factors driving the sedo architecture:

1) AWS Step Functions can be complex to author and test - with often very large config files that are hard to maintain with many developers
2) Workflows need to be composible of other workflows - not a feature originally released with Step Functions (though subsequently supported)
3) A pure serverless event driven based architecture should scale greater and cost less than Step Functions.

Some interesting perspectives (granted, most of these are early 2018/2019 and so may no longer be relevant)

* [Building Serverless State Machines](https://www.stackery.io/blog/serverless-state-machines/)
* [Serverless Steps](https://hackernoon.com/serverless-steps-8a43eac354e1)
* [aws-lambda-fsm-workflows](https://github.com/Workiva/aws-lambda-fsm-workflows/blob/master/docs/OVERVIEW.md)
* [Heavyside](https://github.com/benkehoe/heaviside)
* [Comparison of FaaS Orchestration Systems](https://arxiv.org/pdf/1807.11248.pdf)
* [Serverless Workflow](https://serverlessworkflow.io/)

### Dealing with timeouts

As mentioned in blog post [here](https://medium.com/@zaccharles/there-is-more-than-one-way-to-schedule-a-task-398b4cdc2a75), there are various ways to handle timeouts

1) DynamoDB TTL - see Using DynamoDB TTL as scheduling mechanism scales well, but typically takes ~15mins, can take up to 48 hours
2) SQS Delay Queues - max 15mins for all messages in queue
3) SQS Message Timers
4) SQS Visibility Timeout
5) Step Functions

SQS Delay Queues probably the best approach, with 30 or 60 seconds triggering a timeout processor lambda to perform any evaluation (eg check action state and actual timeout), and then if not actually timed-out, inject new event into the timeout queue.

sedo does not currently separate out processing into separate delay and processing queues, though this approach has been used with success in production elsewhere

### Other Design Considerations

The following should be implemented in a production system (and have been elsewhere...)

* Sedo uses the [Connexion](https://connexion.readthedocs.io/en/latest/) Python framework for Swagger driven APIs.
* Use [React JsonSchema Form](https://rjsf-team.github.io/react-jsonschema-form/) for UI to drive input based on definition inputSchema
* Expand multiple step types, to do actual useful things such as call APIs, transform data etc
* Governance/monitor of executions via separate timeouts
* Human Task steps with their own inputSchemas driving UI forms
* Make use of stash mechanism in between steps and jmespath to transform, so output of one step is input to another
* DynamoDB stream processors to write to Elasticsearch, backed by APIs that allow searching of definitions/executions
* API Authorizors
* audit and history of executions via `execution_history` table 
* Executable conditions / RBAC - who can author definitions and execute them

## Installation

Clone this repo

Install the [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html)

You will need AWS CLI access to a test environment to deploy the SAM application, see 
See https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-envvars.html
If using SAML with Azure, then something like https://github.com/Versent/saml2aws might help

To deploy:

```
cd sedo
sam build
sam deploy --guided
```

The following infrastructure will be created

* `sedo_execution-processor-queue` SQS Queue
* `sedo_definition` DynamoDB Table
* `sedo_execution` DynamoDB Table
* `sedo_execution-processor` Lambda
* `sedo_api` Lambda
* `SedoRestApi` API gateway

**NOTE** NO API Authorizer is currently deployed

## Usage

Once deployed, get your AWS Rest API ID for `sedo-stack` 

```
export INVOKE_URL=https://h4gy3l4e5j.execute-api.us-east-1.amazonaws.com/Prod
```

1) Create definition for tenant 123

```
curl $INVOKE_URL/sedo/tenants/123/definitions -H 'Content-Type: application/json' -d @example-definition.json
{
  "id": "example-definition",
  "tenantId": "123"
}
```

2) List definitions for tenant 123

```
curl $INVOKE_URL/sedo/tenants/123/definitions
[
  {
    "id": "example-definition",
    "tenantId": "123"
  }
]
```

3) Execute definition with invalid input (based on definition inputSchema)

```
$ curl $INVOKE_URL/sedo/tenants/123/definitions/example-definition/execute -H 'Content-Type: application/json' -d '{"input": {"bar":"baz"}}'
{
  "detail": "Additional properties are not allowed ('bar' was unexpected)\n\nFailed validating 'additionalProperties' in schema:\n    {'additionalProperties': False,\n     'properties': {'foo': {'type': 'string'}},\n     'required': ['foo'],\n     'type': 'object'}\n\nOn instance:\n    {'bar': 'baz'}",
  "status": 400,
  "title": "input does not pass inputSchema validation",
  "type": null
}
```

4) Execution definition with valid input

```
$ curl $INVOKE_URL/sedo/tenants/123/definitions/example-definition/execute -H 'Content-Type: application/json' -d '{"input": {"foo":"bar"}}'
{
  "id": "123:example-definition:f5c125a5",
  "state": "ExecutionSubmitted",
  "tenantId": "123"
}
```

5) List running executions

```
$ curl $INVOKE_URL/sedo/tenants/123/executions
[
  {
    "id": "123:example-definition:f5c125a5",
    "state": "StepStarted",
    "step": "wait-some-time",
    "tenantId": "123"
  }
]
```

6) wait a while and then list again (definition wait step is 45 seconds)

```
$ curl $INVOKE_URL/sedo/tenants/123/executions
[
  {
    "id": "123:example-definition:f5c125a5",
    "state": "ExecutionSucceeded",
    "step": "last-echo",
    "tenantId": "123"
  }
]
```