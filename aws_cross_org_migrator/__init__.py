"""Cross-organization AWS account migration toolkit.

Flow implemented here:
  1. New org management account -> InviteAccountToOrganization (per target account)
  2. Old org IAM Identity Center user logs into the AWS access portal
     -> an SSO access token is cached by AWS CLI v2 under ~/.aws/sso/cache
  3. For each target account: read the SSO token, call sso:get_role_credentials
     to obtain temporary credentials *for that account*, then call
     organizations:AcceptHandshake **as the target account** to join the new org.
"""

__version__ = "1.0.0"
