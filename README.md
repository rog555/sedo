# sedo
**S**erverless **E**vent **D**riven **O**rchestrator

The purpose of sedo is to demonstrate how an event driven orchestrator using AWS Lambda, SQS and DynamoDB would work

It is **NOT** intended to be used in production

sedo differs to AWS Step Functions, as it should scale greater and cost less as it is simple lambda and SQS event processing.  Step Functions 

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