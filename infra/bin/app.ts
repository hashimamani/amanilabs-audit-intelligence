#!/usr/bin/env node
import { App, Validations } from 'aws-cdk-lib';
import { AwsSolutionsChecks } from 'cdk-nag';
import { defineStacks } from '../lib/app.js';
import { loadDeployConfig, resolveStage } from '../lib/config.js';

const app = new App();

// cdk-nag runs on every synth through CDK's policy validation framework, so a
// security regression fails CI rather than review.
Validations.of(app).addPlugins(new AwsSolutionsChecks(app));

const stage = resolveStage(app.node.tryGetContext('stage'));
const config = loadDeployConfig(stage);

defineStacks(app, config);

app.synth();
