import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as wafv2 from 'aws-cdk-lib/aws-wafv2';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import { NagSuppressions } from 'cdk-nag';

interface WebappStackProps extends cdk.StackProps {
  portalTitle?: string;
  stackName?: string;
  quicksightIdentityRegion?: string;
  dashboardId?: string;
}

export class WebappStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: WebappStackProps) {
    super(scope, id, props);

    const portalTitle = props?.portalTitle || this.node.tryGetContext('portalTitle') || 'AnyCompany Financial - Operations Portal';
    const stackName = props?.stackName || this.node.tryGetContext('stackName') || 'clearone';
    const quicksightIdentityRegion = props?.quicksightIdentityRegion || this.node.tryGetContext('quicksightIdentityRegion') || this.region;
    const dashboardId = props?.dashboardId || this.node.tryGetContext('dashboardId') || '';
    const chatAgentId = this.node.tryGetContext('chatAgentId') || '';
    const resourcePrefix = stackName;

    // S3 bucket for frontend hosting (private)
    const frontendBucket = new s3.Bucket(this, 'FrontendBucket', {
      bucketName: `${resourcePrefix}-quickchat-frontend`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      serverAccessLogsPrefix: 'access-logs/'
    });

    // CloudFront access logs bucket
    const cfLogsBucket = new s3.Bucket(this, 'CloudFrontLogsBucket', {
      bucketName: `${resourcePrefix}-cloudfront-logs`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      objectOwnership: s3.ObjectOwnership.OBJECT_WRITER
    });

    NagSuppressions.addResourceSuppressions(cfLogsBucket, [
      {
        id: 'AwsSolutions-S1',
        reason: 'This is a logs bucket - enabling access logs on a logs bucket creates circular dependency'
      }
    ]);

    // CloudFront distribution for frontend
    const distribution = new cloudfront.Distribution(this, 'Distribution', {
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(frontendBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
        cachedMethods: cloudfront.CachedMethods.CACHE_GET_HEAD_OPTIONS
      },
      defaultRootObject: 'index.html',
      comment: `${resourcePrefix} QuickChat Portal - Scales to thousands of users`,
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
      minimumProtocolVersion: cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
      enableLogging: true,
      logBucket: cfLogsBucket,
      logFilePrefix: 'cloudfront-logs/'
    });

    NagSuppressions.addResourceSuppressions(distribution, [
      {
        id: 'AwsSolutions-CFR4',
        reason: 'Using default CloudFront certificate with TLS 1.2 minimum - custom certificate not required for this use case'
      }
    ]);

    // Grant CloudFront access to S3 bucket
    frontendBucket.addToResourcePolicy(new iam.PolicyStatement({
      actions: ['s3:GetObject'],
      resources: [frontendBucket.arnForObjects('*')],
      principals: [new iam.ServicePrincipal('cloudfront.amazonaws.com')],
      conditions: {
        'StringEquals': {
          'AWS:SourceArn': `arn:aws:cloudfront::${this.account}:distribution/${distribution.distributionId}`
        }
      }
    }));

    // API Gateway CloudWatch role (required for logging)
    const apiGatewayCloudWatchRole = new iam.Role(this, 'ApiGatewayCloudWatchRole', {
      assumedBy: new iam.ServicePrincipal('apigateway.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonAPIGatewayPushToCloudWatchLogs')
      ]
    });

    NagSuppressions.addResourceSuppressions(apiGatewayCloudWatchRole, [
      {
        id: 'AwsSolutions-IAM4',
        reason: 'AWS managed policy AmazonAPIGatewayPushToCloudWatchLogs is required for API Gateway logging',
        appliesTo: ['Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs']
      }
    ]);

    // Set the CloudWatch role for API Gateway account settings
    // Note: This is an account-level setting. If it already exists, it will be updated.
    const apiGatewayAccount = new apigateway.CfnAccount(this, 'ApiGatewayAccount', {
      cloudWatchRoleArn: apiGatewayCloudWatchRole.roleArn
    });

    // API Gateway with security controls and CORS for CloudFront
    const apiLogGroup = new logs.LogGroup(this, 'ApiGatewayLogGroup', {
      logGroupName: `/aws/apigateway/${resourcePrefix}-quickchat-embed-api`,
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY
    });

    const api: apigateway.RestApi = new apigateway.RestApi(this, 'EmbedApi', {
      restApiName: `${resourcePrefix}-quickchat-embed-api`,
      defaultCorsPreflightOptions: {
        allowOrigins: [
          `https://${distribution.distributionDomainName}`,
          cdk.Fn.join('', [
            'https://',
            cdk.Fn.ref('EmbedApi786D4CBA'),
            '.execute-api.',
            cdk.Aws.REGION,
            '.',
            cdk.Aws.URL_SUFFIX
          ])
        ],
        allowMethods: ['GET', 'POST', 'OPTIONS'],
        allowHeaders: ['Content-Type', 'Authorization'],
        maxAge: cdk.Duration.hours(1)
      },
      deployOptions: {
        loggingLevel: apigateway.MethodLoggingLevel.INFO,
        dataTraceEnabled: false,
        metricsEnabled: true,
        accessLogDestination: new apigateway.LogGroupLogDestination(apiLogGroup),
        accessLogFormat: apigateway.AccessLogFormat.jsonWithStandardFields()
      }
    });

    // Ensure API Gateway account is set up before creating the API
    api.node.addDependency(apiGatewayAccount);

    // WAF for API Gateway protection
    const webAcl = new wafv2.CfnWebACL(this, 'ApiGatewayWAF', {
      name: `${resourcePrefix}-quickchat-waf`,
      scope: 'REGIONAL',
      defaultAction: { allow: {} },
      rules: [
        {
          name: 'RateLimitRule',
          priority: 1,
          statement: {
            rateBasedStatement: {
              limit: 1000,
              aggregateKeyType: 'IP'
            }
          },
          action: { block: {} },
          visibilityConfig: {
            sampledRequestsEnabled: true,
            cloudWatchMetricsEnabled: true,
            metricName: 'RateLimitRule'
          }
        }
      ],
      visibilityConfig: {
        sampledRequestsEnabled: true,
        cloudWatchMetricsEnabled: true,
        metricName: 'WebACL'
      }
    });

    // Associate WAF with API Gateway
    new wafv2.CfnWebACLAssociation(this, 'WebACLAssociation', {
      resourceArn: api.deploymentStage.stageArn,
      webAclArn: webAcl.attrArn
    });

    // Cognito User Pool with strong security
    const userPool = new cognito.UserPool(this, 'UserPool', {
      userPoolName: `${resourcePrefix}-quickchat-pool`,
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      autoVerify: { email: true },
      passwordPolicy: {
        minLength: 12,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: true,
        tempPasswordValidity: cdk.Duration.days(3)
      },
      mfa: cognito.Mfa.OPTIONAL,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      userInvitation: {
        emailSubject: `Your ${portalTitle} Account Has Been Created`,
        emailBody: `Hello,\n\nYour account for ${portalTitle} has been created by your administrator.\n\nLogin Credentials:\n• Portal URL: https://${distribution.distributionDomainName}\n• Username: {username}\n• Temporary Password: {####}\n\nSecurity Requirements:\n• You must change your password upon first login\n• Your temporary password expires in 3 days\n• Passwords must be at least 12 characters with uppercase, lowercase, numbers, and symbols\n\nImportant:\n• Do not share your credentials with anyone\n• If you did not request this account, please contact your administrator immediately\n\nFor assistance, contact your system administrator.\n\nBest regards,\n${portalTitle} Team`
      }
    });

    const userPoolClient = new cognito.UserPoolClient(this, 'UserPoolClient', {
      userPool,
      userPoolClientName: `${resourcePrefix}-quickchat-client`,
      generateSecret: false,
      authFlows: {
        userPassword: false, // Disable for security
        userSrp: true,
        custom: false,
        adminUserPassword: false
      },
      oAuth: {
        flows: {
          authorizationCodeGrant: true,
          implicitCodeGrant: false  // More secure authorization code flow
        },
        scopes: [
          cognito.OAuthScope.OPENID,
          cognito.OAuthScope.PROFILE
        ],
        callbackUrls: [
          `https://${distribution.distributionDomainName}`,
          cdk.Fn.join('', [
            'https://',
            api.restApiId,
            '.execute-api.',
            cdk.Aws.REGION,
            '.',
            cdk.Aws.URL_SUFFIX,
            '/prod/embed-sample'
          ])
        ],
        logoutUrls: [
          `https://${distribution.distributionDomainName}`,
          cdk.Fn.join('', [
            'https://',
            api.restApiId,
            '.execute-api.',
            cdk.Aws.REGION,
            '.',
            cdk.Aws.URL_SUFFIX,
            '/prod/embed-sample'
          ])
        ]
      },
      supportedIdentityProviders: [
        cognito.UserPoolClientIdentityProvider.COGNITO
      ],
      refreshTokenValidity: cdk.Duration.hours(8),
      accessTokenValidity: cdk.Duration.hours(1),
      idTokenValidity: cdk.Duration.hours(1)
    });

    // Cognito Domain for OAuth endpoints
    const cognitoDomain = new cognito.UserPoolDomain(this, 'CognitoDomain', {
      userPool,
      cognitoDomain: {
        domainPrefix: `${resourcePrefix}-quickchat`
      }
    });

    // OIDC Identity Provider with dynamic thumbprint fetching
    const oidcProvider = new iam.OpenIdConnectProvider(this, 'CognitoOIDCProvider', {
      url: `https://cognito-idp.${this.region}.amazonaws.com/${userPool.userPoolId}`,
      clientIds: [userPoolClient.userPoolClientId]
      // Thumbprints will be automatically fetched by CDK
    });

    // Web Identity Role with session duration limits
    const webIdentityRole = new iam.Role(this, 'WebIdentityRole', {
      roleName: `${stackName}-quicksuite-web-identity-role`,
      assumedBy: new iam.WebIdentityPrincipal(oidcProvider.openIdConnectProviderArn),
      maxSessionDuration: cdk.Duration.hours(1),
      inlinePolicies: {
        QuickSuiteAccess: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: [
                'quicksight:GenerateEmbedUrlForRegisteredUser',
                'quicksight:ListUsers'
              ],
              resources: [
                `arn:aws:quicksight:us-east-1:${cdk.Aws.ACCOUNT_ID}:user/default/*`,
                `arn:aws:quicksight:us-east-1:${cdk.Aws.ACCOUNT_ID}:namespace/default`,
                `arn:aws:quicksight:us-east-1:${cdk.Aws.ACCOUNT_ID}:dashboard/*`,
                `arn:aws:quicksight:us-west-2:${cdk.Aws.ACCOUNT_ID}:user/default/*`,
                `arn:aws:quicksight:us-west-2:${cdk.Aws.ACCOUNT_ID}:namespace/default`,
                `arn:aws:quicksight:us-west-2:${cdk.Aws.ACCOUNT_ID}:dashboard/*`,
                `arn:aws:quicksight:ap-southeast-2:${cdk.Aws.ACCOUNT_ID}:user/default/*`,
                `arn:aws:quicksight:ap-southeast-2:${cdk.Aws.ACCOUNT_ID}:namespace/default`,
                `arn:aws:quicksight:ap-southeast-2:${cdk.Aws.ACCOUNT_ID}:dashboard/*`,
                `arn:aws:quicksight:eu-west-1:${cdk.Aws.ACCOUNT_ID}:user/default/*`,
                `arn:aws:quicksight:eu-west-1:${cdk.Aws.ACCOUNT_ID}:namespace/default`,
                `arn:aws:quicksight:eu-west-1:${cdk.Aws.ACCOUNT_ID}:dashboard/*`
              ]
            })
          ]
        })
      }
    });

    // Lambda execution role with minimal permissions
    const lambdaLogGroup = new logs.LogGroup(this, 'EmbedLambdaLogGroup', {
      logGroupName: `/aws/lambda/${resourcePrefix}-quickchat-embed-function`,
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY
    });

    const lambdaRole = new iam.Role(this, 'EmbedLambdaRole', {
      roleName: `${stackName}-quickchat-embed-lambda-role`,
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      inlinePolicies: {
        CloudWatchLogs: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: ['logs:CreateLogStream', 'logs:PutLogEvents'],
              resources: [lambdaLogGroup.logGroupArn]
            })
          ]
        }),
        AssumeRoleOnly: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: ['sts:AssumeRoleWithWebIdentity'],
              resources: [webIdentityRole.roleArn]
            })
          ]
        })
      }
    });

    // Lambda function for QuickChat API
    const embedLambda = new lambda.Function(this, 'EmbedLambda', {
      functionName: `${resourcePrefix}-quickchat-embed-function`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'embed_oidc_federation.lambda_handler',
      architecture: lambda.Architecture.ARM_64,
      logGroup: lambdaLogGroup,
      code: lambda.Code.fromAsset('../lambda', {
        exclude: ['build', '__pycache__', '*.pyc'],
        bundling: {
          image: lambda.Runtime.PYTHON_3_12.bundlingImage,
          platform: 'linux/arm64',
          command: [
            'bash', '-c',
            'pip install -r requirements.txt -t /asset-output && cp -au embed_oidc_federation.py /asset-output'
          ]
        }
      }),
      role: lambdaRole,
      timeout: cdk.Duration.seconds(30),
      memorySize: 512,
      reservedConcurrentExecutions: 100,
      environment: {
        COGNITO_CLIENT_ID: userPoolClient.userPoolClientId,
        COGNITO_USER_POOL_ID: userPool.userPoolId,
        COGNITO_DOMAIN_URL: `https://${cognitoDomain.domainName}.auth.${this.region}.amazoncognito.com`,
        WEB_IDENTITY_ROLE_ARN: webIdentityRole.roleArn,
        ALLOWED_ORIGIN: `https://${distribution.distributionDomainName}`,
        REDIRECT_URI: `https://${distribution.distributionDomainName}`,
        CLOUDFRONT_DOMAIN: distribution.distributionDomainName,
        QUICKSIGHT_IDENTITY_REGION: quicksightIdentityRegion,
        DASHBOARD_ID: dashboardId,
        CHAT_AGENT_ID: chatAgentId
      }
    });

    const integration = new apigateway.LambdaIntegration(embedLambda, {
      proxy: true
    });
    
    const embedSampleResource = api.root.addResource('embed-sample');
    const getMethod = embedSampleResource.addMethod('GET', integration, {
      authorizationType: apigateway.AuthorizationType.NONE,
      requestValidator: new apigateway.RequestValidator(this, 'RequestValidator', {
        restApi: api,
        requestValidatorName: `${resourcePrefix}-request-validator`,
        validateRequestBody: true,
        validateRequestParameters: true
      })
    });

    // CDK Nag Suppressions
    NagSuppressions.addResourceSuppressions(getMethod, [
      {
        id: 'AwsSolutions-APIG4',
        reason: 'Authentication handled by Cognito OAuth flow in application layer - ID token validated in Lambda'
      },
      {
        id: 'AwsSolutions-COG4',
        reason: 'Using custom OAuth flow with Cognito - ID token validation in Lambda instead of API Gateway authorizer'
      }
    ]);

    NagSuppressions.addStackSuppressions(this, [
      {
        id: 'AwsSolutions-COG2',
        reason: 'MFA is optional - can be enabled per user requirement'
      },
      {
        id: 'AwsSolutions-COG3',
        reason: 'AdvancedSecurityMode is deprecated - using standard Cognito security features'
      },
      {
        id: 'AwsSolutions-CFR1',
        reason: 'Geo restrictions not required for this use case - can be added based on customer requirements'
      },
      {
        id: 'AwsSolutions-CFR2',
        reason: 'CloudFront does not need WAF - API Gateway already has WAF protection'
      }
    ]);

    // Outputs
    new cdk.CfnOutput(this, 'ApiGatewayURL', {
      value: `${api.url}embed-sample`,
      description: 'API Gateway URL for QuickChat embedding'
    });

    new cdk.CfnOutput(this, 'CognitoUserPoolId', {
      value: userPool.userPoolId,
      description: 'Cognito User Pool ID'
    });

    new cdk.CfnOutput(this, 'CognitoClientId', {
      value: userPoolClient.userPoolClientId,
      description: 'Cognito User Pool Client ID'
    });

    new cdk.CfnOutput(this, 'CognitoDomainUrl', {
      value: `https://${cognitoDomain.domainName}.auth.${this.region}.amazoncognito.com`,
      description: 'Cognito OAuth domain URL'
    });

    new cdk.CfnOutput(this, 'OIDCProviderArn', {
      value: oidcProvider.openIdConnectProviderArn,
      description: 'OIDC Provider ARN for Cognito federation'
    });

    new cdk.CfnOutput(this, 'WebIdentityRoleArn', {
      value: webIdentityRole.roleArn,
      description: 'Web Identity Role ARN for federated users'
    });

    new cdk.CfnOutput(this, 'PortalTitle', {
      value: portalTitle,
      description: 'Portal title displayed in web application'
    });

    new cdk.CfnOutput(this, 'ApiDomain', {
      value: `${api.restApiId}.execute-api.${this.region}.amazonaws.com`,
      description: 'API Gateway domain for QuickSight allowlist'
    });

    new cdk.CfnOutput(this, 'CloudFrontURL', {
      value: `https://${distribution.distributionDomainName}`,
      description: 'CloudFront URL for accessing the web portal'
    });

    new cdk.CfnOutput(this, 'CloudFrontDomain', {
      value: distribution.distributionDomainName,
      description: 'CloudFront domain for QuickSight allowlist'
    });

    new cdk.CfnOutput(this, 'FrontendBucketName', {
      value: frontendBucket.bucketName,
      description: 'S3 bucket name for frontend files'
    });

    new cdk.CfnOutput(this, 'Region', {
      value: this.region,
      description: 'AWS region where resources are deployed'
    });

    new cdk.CfnOutput(this, 'AWSProfile', {
      value: process.env.AWS_PROFILE || 'default',
      description: 'AWS CLI profile used for deployment'
    });

    new cdk.CfnOutput(this, 'QuickSightIdentityRegion', {
      value: quicksightIdentityRegion,
      description: 'QuickSight identity region'
    });

    new cdk.CfnOutput(this, 'DashboardId', {
      value: dashboardId,
      description: 'Quick Suite Dashboard ID wired into the embed Lambda'
    });

    // Deploy frontend files to S3 (built React bundle from my-app/dist)
    const deployment = new s3deploy.BucketDeployment(this, 'DeployFrontend', {
      sources: [s3deploy.Source.asset('../my-app/dist')],
      destinationBucket: frontendBucket,
      distribution,
      distributionPaths: ['/*']
    });

    // CDK Nag Suppressions
    NagSuppressions.addResourceSuppressions(embedLambda, [
      {
        id: 'AwsSolutions-L1',
        reason: 'Python 3.12 is the latest stable runtime version available'
      }
    ]);

    NagSuppressions.addResourceSuppressions(webIdentityRole, [
      {
        id: 'AwsSolutions-IAM5',
        reason: 'Wildcard in resource path required for QuickSight user federation (user ARN resolved at runtime) and dashboard embedding across the 4 QuickSight embedded regions: us-east-1, us-west-2, ap-southeast-2, eu-west-1',
        appliesTo: [
          'Resource::arn:aws:quicksight:us-east-1:<AWS::AccountId>:user/default/*',
          'Resource::arn:aws:quicksight:us-west-2:<AWS::AccountId>:user/default/*',
          'Resource::arn:aws:quicksight:ap-southeast-2:<AWS::AccountId>:user/default/*',
          'Resource::arn:aws:quicksight:eu-west-1:<AWS::AccountId>:user/default/*',
          'Resource::arn:aws:quicksight:us-east-1:<AWS::AccountId>:dashboard/*',
          'Resource::arn:aws:quicksight:us-west-2:<AWS::AccountId>:dashboard/*',
          'Resource::arn:aws:quicksight:ap-southeast-2:<AWS::AccountId>:dashboard/*',
          'Resource::arn:aws:quicksight:eu-west-1:<AWS::AccountId>:dashboard/*'
        ]
      }
    ]);

    NagSuppressions.addStackSuppressions(this, [
      {
        id: 'AwsSolutions-IAM4',
        reason: 'CDK BucketDeployment construct requires AWS managed policy for Lambda execution',
        appliesTo: ['Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole']
      },
      {
        id: 'AwsSolutions-IAM5',
        reason: 'CDK BucketDeployment requires wildcard permissions for S3 operations during deployment',
        appliesTo: [
          'Action::s3:GetBucket*',
          'Action::s3:GetObject*',
          'Action::s3:List*',
          'Action::s3:Abort*',
          'Action::s3:DeleteObject*',
          'Resource::arn:<AWS::Partition>:s3:::cdk-hnb659fds-assets-<AWS::AccountId>-<AWS::Region>/*',
          { regex: '/^Resource::arn:aws:s3:::cdk-hnb659fds-assets-.*/' },
          'Resource::<FrontendBucketEFE2E19C.Arn>/*',
          'Resource::*'
        ]
      },
      {
        id: 'AwsSolutions-L1',
        reason: 'CDK BucketDeployment Lambda is managed by CDK framework'
      }
    ]);
  }
}