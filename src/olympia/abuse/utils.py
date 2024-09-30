from django.conf import settings

from jira import JIRA


def report_decision_to_jira(decision):
    jira_instance = JIRA(
        settings.JIRA_HOST,
        basic_auth=(settings.JIRA_API_USERNAME, settings.JIRA_API_TOKEN),
        validate=True,
    )

    addon_name = str(decision.addon.name)
    policies = ', '.join(policy.name for policy in decision.policies.all())
    jira_instance.create_issue(
        project='AMOENG',
        summary=f'Escalation for Add-on "{addon_name}"',
        description=f'Add-on "{addon_name}" {decision.get_action_display()} action, '
        f'under policies: [{policies}], '
        f'with additional reasoning "{decision.notes}". '
        'Escalated for review due to membership of Promoted Notable group',
        issuetype={'name': 'Spike'},
    )
