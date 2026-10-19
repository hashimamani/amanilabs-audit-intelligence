import { CfnOutput, Duration, RemovalPolicy, Stack, Validations, type StackProps } from 'aws-cdk-lib';
import {
  AccountRecovery,
  CfnUserPoolGroup,
  FeaturePlan,
  Mfa,
  StringAttribute,
  UserPool,
  UserPoolClient,
  UserPoolEmail,
} from 'aws-cdk-lib/aws-cognito';
import type { Construct } from 'constructs';
import { isProtectedStage, resourceName, type DeployConfig } from '../config.js';

export interface AuthStackProps extends StackProps {
  readonly config: DeployConfig;
}

export const ROLES = ['admin', 'auditor'] as const;

/**
 * Identity. Cognito is the authority for who a person is; the role is the
 * group they are in (`cognito:groups` on every token) and the SACCO they
 * belong to is the immutable `custom:tenant` attribute on the ID token.
 *
 * There is no public sign-up. Accounts exist only because an administrator
 * created one.
 */
export class AuthStack extends Stack {
  readonly userPool: UserPool;
  readonly userPoolClient: UserPoolClient;

  constructor(scope: Construct, id: string, props: AuthStackProps) {
    super(scope, id, props);
    const { config } = props;
    const protectedStage = isProtectedStage(config.stage);

    this.userPool = new UserPool(this, 'UserPool', {
      userPoolName: resourceName(config, 'users'),
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      signInCaseSensitive: false,
      autoVerify: { email: true },
      standardAttributes: {
        email: { required: true, mutable: true },
        fullname: { required: true, mutable: true },
      },
      customAttributes: {
        // Set once at creation by the API; a user never moves between SACCOs.
        tenant: new StringAttribute({ minLen: 1, maxLen: 64, mutable: false }),
      },
      passwordPolicy: {
        minLength: 12,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: true,
        tempPasswordValidity: Duration.days(7),
      },
      mfa: config.requireMfa ? Mfa.REQUIRED : Mfa.OPTIONAL,
      mfaSecondFactor: { sms: false, otp: true },
      accountRecovery: AccountRecovery.EMAIL_ONLY,
      email: UserPoolEmail.withCognito(),
      featurePlan: FeaturePlan.ESSENTIALS,
      userInvitation: {
        emailSubject: 'Your Audit Intelligence account',
        emailBody: [
          'Hello,',
          '',
          'An Audit Intelligence account has been created for {username}.',
          '',
          'Your temporary password is: {####}',
          '',
          'Sign in with your email address and this password. You will be asked to',
          'choose your own password straight away.',
        ].join('<br />'),
      },
      removalPolicy: protectedStage ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY,
      deletionProtection: protectedStage,
    });

    Validations.of(this.userPool).acknowledge({
      id: 'AwsSolutions-COG2',
      reason:
        'MFA is required when requireMfa is set (the production configuration) and optional ' +
        'otherwise, so a dev deployment does not need an authenticator enrolled to be exercised. ' +
        'Mitigations everywhere: no public sign-up, accounts created only by an administrator, ' +
        'one-hour tokens with revocation, and disabling an account cuts access on the next request.',
    });
    Validations.of(this.userPool).acknowledge({
      id: 'AwsSolutions-COG8',
      reason:
        'The Plus feature plan is a per-active-user charge whose extra features (threat ' +
        'protection, adaptive authentication) target pools with public sign-up. Every account ' +
        'here is created by an administrator. Revisit with the user count.',
    });
    Validations.of(this.userPool).acknowledge({
      id: 'AwsSolutions-COG3',
      reason:
        'Threat protection is part of the Cognito Plus feature plan, a per-active-user charge ' +
        'aimed at pools with public sign-up and credential-stuffing exposure. This pool has ' +
        'neither. Revisit when a SACCO asks for it or the user count justifies the cost.',
    });

    for (const [index, role] of ROLES.entries()) {
      new CfnUserPoolGroup(this, `Group-${role}`, {
        userPoolId: this.userPool.userPoolId,
        groupName: role,
        description: role === 'admin' ? 'Manages the SACCO\'s users; everything an auditor can do' : 'Works cases, runs analyses',
        precedence: index,
      });
    }

    this.userPoolClient = new UserPoolClient(this, 'WebClient', {
      userPool: this.userPool,
      userPoolClientName: resourceName(config, 'web'),
      // A browser cannot keep a secret, so there is none to leak.
      generateSecret: false,
      authFlows: { userSrp: true },
      accessTokenValidity: Duration.hours(1),
      idTokenValidity: Duration.hours(1),
      refreshTokenValidity: Duration.days(30),
      enableTokenRevocation: true,
      // Do not reveal whether an email address has an account.
      preventUserExistenceErrors: true,
    });

    new CfnOutput(this, 'UserPoolId', { value: this.userPool.userPoolId });
    new CfnOutput(this, 'UserPoolClientId', { value: this.userPoolClient.userPoolClientId });
  }
}
