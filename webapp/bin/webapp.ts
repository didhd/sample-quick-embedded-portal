#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { WebappStack } from '../lib/webapp-stack';
import { AwsSolutionsChecks } from 'cdk-nag';
import { Aspects } from 'aws-cdk-lib';

const app = new cdk.App();
const stackName = app.node.tryGetContext('stackName') || 'WebappStack';

// Get region and account - MUST be set for region to work correctly
const region = process.env.CDK_DEFAULT_REGION;
const account = process.env.CDK_DEFAULT_ACCOUNT;

if (!region || !account) {
  throw new Error('Both CDK_DEFAULT_REGION and CDK_DEFAULT_ACCOUNT must be set');
}

new WebappStack(app, stackName, {
  env: {
    region: region,
    account: account
  }
});

// Add CDK Nag AWS Solutions security checks
Aspects.of(app).add(new AwsSolutionsChecks({ verbose: true }));