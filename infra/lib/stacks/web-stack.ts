import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { CfnOutput, Duration, RemovalPolicy, Stack, Validations, type CfnResource, type StackProps } from 'aws-cdk-lib';
import {
  AllowedMethods,
  CachePolicy,
  Distribution,
  Function as CloudFrontFunction,
  FunctionCode,
  FunctionEventType,
  HeadersFrameOption,
  HeadersReferrerPolicy,
  HttpVersion,
  OriginRequestPolicy,
  PriceClass,
  ResponseHeadersPolicy,
  ViewerProtocolPolicy,
} from 'aws-cdk-lib/aws-cloudfront';
import { HttpOrigin, S3BucketOrigin } from 'aws-cdk-lib/aws-cloudfront-origins';
import { BlockPublicAccess, Bucket, BucketEncryption, type IBucket } from 'aws-cdk-lib/aws-s3';
import { BucketDeployment, Source } from 'aws-cdk-lib/aws-s3-deployment';
import type { Construct } from 'constructs';
import { API_BASE_PATH, datasetsBucketName, isProtectedStage, type DeployConfig } from '../config.js';

const FRONTEND_DIST = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', 'audit_intelligence', 'frontend', 'dist');

export interface WebStackProps extends StackProps {
  readonly config: DeployConfig;
  /** Host name only, no scheme - CloudFront origins do not take one. */
  readonly apiEndpointHost: string;
  readonly accessLogsBucket: IBucket;
  readonly userPoolId: string;
  readonly userPoolClientId: string;
}

/**
 * The app: a private bucket behind CloudFront, which also fronts the API
 * under /api/* so the app and its API are one origin - no CORS anywhere.
 */
export class WebStack extends Stack {
  readonly distribution: Distribution;
  readonly siteBucket: Bucket;

  constructor(scope: Construct, id: string, props: WebStackProps) {
    super(scope, id, props);
    const { config } = props;

    this.siteBucket = new Bucket(this, 'SiteBucket', {
      encryption: BucketEncryption.S3_MANAGED,
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      // A build artefact: rebuilt from the repository, never recovered.
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      serverAccessLogsBucket: props.accessLogsBucket,
      serverAccessLogsPrefix: 'site/',
    });

    /**
     * Single-page app routing, attached only to the default behaviour so an
     * API 404 is never rewritten into index.html.
     */
    const spaRouting = new CloudFrontFunction(this, 'SpaRouting', {
      comment: 'Serve index.html for app routes, leave file requests alone',
      code: FunctionCode.fromInline(`
function handler(event) {
  var request = event.request;
  if (request.uri.indexOf('.') === -1) {
    request.uri = '/index.html';
  }
  return request;
}
      `),
    });

    const datasetsHost = `https://${datasetsBucketName(config)}.s3.${this.region}.amazonaws.com`;
    const securityHeaders = new ResponseHeadersPolicy(this, 'SecurityHeaders', {
      comment: 'Security headers for the Audit Intelligence app',
      securityHeadersBehavior: {
        contentSecurityPolicy: {
          override: true,
          contentSecurityPolicy: [
            "default-src 'self'",
            "script-src 'self'",
            // Vite emits a small amount of inline style; scripts are not inlined.
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data:",
            // Cognito for sign-in, the datasets bucket for presigned uploads.
            `connect-src 'self' https://cognito-idp.${this.region}.amazonaws.com ${datasetsHost}`,
            "font-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
            'upgrade-insecure-requests',
          ].join('; '),
        },
        contentTypeOptions: { override: true },
        frameOptions: { frameOption: HeadersFrameOption.DENY, override: true },
        referrerPolicy: { referrerPolicy: HeadersReferrerPolicy.STRICT_ORIGIN_WHEN_CROSS_ORIGIN, override: true },
        strictTransportSecurity: { accessControlMaxAge: Duration.days(365), includeSubdomains: true, override: true },
      },
    });

    this.distribution = new Distribution(this, 'Distribution', {
      comment: `Audit Intelligence (${config.stage})`,
      defaultRootObject: 'index.html',
      // Includes the Nairobi edge; PRICE_CLASS_100 would serve Kenya from Europe.
      priceClass: PriceClass.PRICE_CLASS_200,
      httpVersion: HttpVersion.HTTP2_AND_3,
      enableLogging: true,
      logBucket: props.accessLogsBucket,
      logFilePrefix: 'cloudfront/',
      defaultBehavior: {
        origin: S3BucketOrigin.withOriginAccessControl(this.siteBucket),
        viewerProtocolPolicy: ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        allowedMethods: AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
        cachePolicy: CachePolicy.CACHING_OPTIMIZED,
        responseHeadersPolicy: securityHeaders,
        compress: true,
        functionAssociations: [{ function: spaRouting, eventType: FunctionEventType.VIEWER_REQUEST }],
      },
      additionalBehaviors: {
        [`${API_BASE_PATH}/*`]: {
          origin: new HttpOrigin(props.apiEndpointHost, { readTimeout: Duration.seconds(30) }),
          viewerProtocolPolicy: ViewerProtocolPolicy.HTTPS_ONLY,
          allowedMethods: AllowedMethods.ALLOW_ALL,
          // Per-user responses are never cached at the edge.
          cachePolicy: CachePolicy.CACHING_DISABLED,
          // Forwards Authorization for the JWT authorizer, not Host (the gateway needs its own).
          originRequestPolicy: OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
          compress: true,
        },
      },
    });

    Validations.of(this.distribution).acknowledge({
      id: 'AwsSolutions-CFR4',
      reason:
        'The default CloudFront certificate pins the viewer security policy to TLSv1 regardless ' +
        'of minimumProtocolVersion. Resolved by the custom domain and ACM certificate, which ' +
        'arrive once a domain exists (phase 4).',
    });
    Validations.of(this.distribution).acknowledge({
      id: 'AwsSolutions-CFR1',
      reason:
        'Geo restriction would lock out an auditor travelling more often than it would stop an ' +
        'attacker, who changes country trivially. Every API request is authenticated per request.',
    });
    Validations.of(this.distribution).acknowledge({
      id: 'AwsSolutions-CFR2',
      reason:
        'WAF costs more per month than the rest of this platform to protect an API where every ' +
        'route already requires a valid Cognito JWT and there is no public sign-up. API Gateway ' +
        'per-route throttling is configured instead, at no cost.',
    });

    /**
     * Runtime configuration, fetched by the app at boot rather than compiled
     * into the bundle, so one build is valid in every stage.
     */
    const runtimeConfig = Source.jsonData('config.json', {
      stage: config.stage,
      region: this.region,
      userPoolId: props.userPoolId,
      userPoolClientId: props.userPoolClientId,
      apiBasePath: API_BASE_PATH,
    });

    const appBuilt = existsSync(join(FRONTEND_DIST, 'index.html'));
    const deployment = new BucketDeployment(this, 'DeployApp', {
      destinationBucket: this.siteBucket,
      distribution: this.distribution,
      distributionPaths: ['/index.html', '/config.json'],
      prune: true,
      sources: [
        appBuilt
          ? Source.asset(FRONTEND_DIST)
          : // `cdk synth` must work in a clean checkout, before the frontend is built.
            Source.data('index.html', '<!doctype html><title>Audit Intelligence</title><p>Build the frontend and deploy again.</p>'),
        // Last, so the real configuration wins over anything of the same name in the build.
        runtimeConfig,
      ],
    });

    /**
     * BucketDeployment is a CDK-provided custom resource: its wildcard S3
     * permissions come from the aws-s3-deployment library and cannot be
     * narrowed here. It runs only during a deployment, reads the CDK assets
     * bucket and rewrites the site bucket, and invalidates the distribution.
     */
    const siteBucketLogicalId = Stack.of(this).getLogicalId(this.siteBucket.node.defaultChild as CfnResource);
    const libraryWildcards = [
      'Action::s3:GetObject*',
      'Action::s3:GetBucket*',
      'Action::s3:List*',
      'Action::s3:DeleteObject*',
      'Action::s3:Abort*',
      // Rendered with the partition token in an environment-agnostic synth and
      // with the literal partition once the account is pinned; both are acknowledged.
      `Resource::arn:<AWS::Partition>:s3:::cdk-hnb659fds-assets-${config.account}-${config.region}/*`,
      `Resource::arn:aws:s3:::cdk-hnb659fds-assets-${config.account}-${config.region}/*`,
      `Resource::<${siteBucketLogicalId}.Arn>/*`,
      'Resource::*',
    ];
    for (const node of this.node.findAll()) {
      if (!node.node.id.startsWith('Custom::CDKBucketDeployment')) continue;
      Validations.of(node).acknowledge({
        id: 'AwsSolutions-L1',
        reason: 'CDK-managed custom resource; its runtime is pinned by the aws-s3-deployment library version.',
      });
      Validations.of(node).acknowledge({
        id: 'AwsSolutions-IAM4[Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole]',
        reason: 'CDK-managed custom resource; its execution role is created by the aws-s3-deployment library.',
      });
      for (const detail of libraryWildcards) {
        Validations.of(node).acknowledge({
          id: `AwsSolutions-IAM5[${detail}]`,
          reason:
            'CDK-managed custom resource. It must read the CDK assets bucket, write and prune ' +
            'the whole site bucket, and invalidate the distribution (an API with no resource ' +
            'ARN); the wildcards are generated by the aws-s3-deployment library.',
        });
      }
    }
    void deployment;

    new CfnOutput(this, 'AppUrl', { value: `https://${this.distribution.distributionDomainName}` });
    new CfnOutput(this, 'DistributionId', { value: this.distribution.distributionId });
  }

  static get frontendDist(): string {
    return FRONTEND_DIST;
  }
}

export const isWebAppBuilt = (): boolean => existsSync(join(FRONTEND_DIST, 'index.html'));
export { isProtectedStage };
