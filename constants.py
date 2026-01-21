import os
from aws_cdk import Environment



# Dev Environment
DEV_ENV = Environment( account=os.environ["CDK_DEFAULT_ACCOUNT"], region=os.environ["CDK_DEFAULT_REGION"])
DEV_CONFIG = {
    "AWS_REGION" :  'us-east-1',
    "AWS_BUCKET" :  'omics-eventbridge-solution-dev',
    "JOB_TIMEOUT" : 1500,  # seconds
}


 