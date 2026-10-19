import { CfnOutput, Duration, Stack, Validations, type StackProps } from 'aws-cdk-lib';
import {
  type Alarm,
  AlarmRule,
  AlarmState,
  AlarmStatusWidget,
  CompositeAlarm,
  Dashboard,
  GraphWidget,
  type IMetric,
  TextWidget,
} from 'aws-cdk-lib/aws-cloudwatch';
import { SnsAction } from 'aws-cdk-lib/aws-cloudwatch-actions';
import { Topic } from 'aws-cdk-lib/aws-sns';
import { EmailSubscription } from 'aws-cdk-lib/aws-sns-subscriptions';
import type { Construct } from 'constructs';
import { resourceName, type DeployConfig } from '../config.js';

export interface OpsStackProps extends StackProps {
  readonly config: DeployConfig;
  readonly alarms: Alarm[];
  readonly apiRequests: IMetric;
  readonly apiLatency: IMetric;
  readonly apiServerErrors: IMetric;
  readonly functionDurations: IMetric[];
  readonly queueDepth: IMetric;
  readonly tableReadCapacity: IMetric;
  readonly tableWriteCapacity: IMetric;
}

/**
 * One dashboard and one place that notifies. The alarms live beside the
 * resources they watch; here they roll into a single composite alarm so an
 * incident produces one email rather than six.
 */
export class OpsStack extends Stack {
  readonly alarmTopic: Topic;

  constructor(scope: Construct, id: string, props: OpsStackProps) {
    super(scope, id, props);
    const { config } = props;

    this.alarmTopic = new Topic(this, 'AlarmTopic', {
      topicName: resourceName(config, 'alarms'),
      displayName: `Audit Intelligence ${config.stage} alarms`,
      enforceSSL: true,
    });
    Validations.of(this.alarmTopic).acknowledge({
      id: 'AwsSolutions-SNS2',
      reason:
        'Alarm notifications carry an alarm name and state, no member data. CloudWatch alarms ' +
        'cannot publish to a topic encrypted with the AWS-managed SNS key, and a customer-managed ' +
        'key would be a fixed monthly cost to encrypt the words "ALARM" and "OK".',
    });
    // The subscriber must confirm by clicking the link AWS emails them.
    this.alarmTopic.addSubscription(new EmailSubscription(config.alarmEmail));

    const unhealthy = new CompositeAlarm(this, 'Unhealthy', {
      compositeAlarmName: resourceName(config, 'unhealthy'),
      alarmDescription: 'One or more Audit Intelligence health checks are in alarm',
      alarmRule: AlarmRule.anyOf(...props.alarms.map((a) => AlarmRule.fromAlarm(a, AlarmState.ALARM))),
    });
    unhealthy.addAlarmAction(new SnsAction(this.alarmTopic));
    unhealthy.addOkAction(new SnsAction(this.alarmTopic));

    const dashboard = new Dashboard(this, 'Dashboard', {
      dashboardName: resourceName(config, 'ops'),
      defaultInterval: Duration.days(1),
    });
    dashboard.addWidgets(
      new TextWidget({
        markdown: [
          `# Audit Intelligence — ${config.stage}`,
          '',
          'The API, the worker behind the jobs queue, and the table underneath.',
          'Flat lines outside office hours are expected: nothing runs when nobody is auditing.',
        ].join('\n'),
        width: 24,
        height: 3,
      }),
    );
    dashboard.addWidgets(new AlarmStatusWidget({ title: 'Health checks', alarms: [unhealthy, ...props.alarms], width: 24, height: 4 }));
    dashboard.addWidgets(
      new GraphWidget({ title: 'API requests', left: [props.apiRequests], right: [props.apiServerErrors], width: 12, height: 6 }),
      new GraphWidget({
        title: 'API latency (p99)',
        left: [props.apiLatency],
        leftAnnotations: [{ value: 5000, label: 'Feels broken', color: '#d13212' }],
        width: 12,
        height: 6,
      }),
    );
    dashboard.addWidgets(
      new GraphWidget({ title: 'Function duration (p99)', left: props.functionDurations, width: 8, height: 6 }),
      new GraphWidget({ title: 'Jobs waiting', left: [props.queueDepth], width: 8, height: 6 }),
      new GraphWidget({ title: 'Table capacity consumed', left: [props.tableReadCapacity, props.tableWriteCapacity], width: 8, height: 6 }),
    );

    new CfnOutput(this, 'AlarmTopicArn', { value: this.alarmTopic.topicArn });
    new CfnOutput(this, 'DashboardName', { value: resourceName(config, 'ops') });
  }
}
