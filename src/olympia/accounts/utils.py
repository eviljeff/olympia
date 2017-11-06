import json
import os
# from base64 import b64encode, urlsafe_b64encode
from base64 import urlsafe_b64encode
from datetime import datetime
from urllib import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect
from django.utils.http import is_safe_url

from kombu import Connection, Queue
from kombu.mixins import ConsumerMixin
from kombu.transport import SQS

from olympia.core.logger import getLogger
from olympia.accounts.tasks import primary_email_change_event


def fxa_config(request):
    config = {camel_case(key): value
              for key, value in settings.FXA_CONFIG['default'].iteritems()
              if key != 'client_secret'}
    if request.user.is_authenticated():
        config['email'] = request.user.email
    request.session.setdefault('fxa_state', generate_fxa_state())
    config['state'] = request.session['fxa_state']
    return config


def fxa_login_url(config, state, next_path=None, action=None):
    if next_path and is_safe_url(next_path):
        state += ':' + urlsafe_b64encode(next_path.encode('utf-8')).rstrip('=')
    query = {
        'client_id': config['client_id'],
        'redirect_url': config['redirect_url'],
        'scope': config['scope'],
        'state': state,
    }
    if action is not None:
        query['action'] = action
    return '{host}/authorization?{query}'.format(
        host=config['oauth_host'], query=urlencode(query))


def default_fxa_register_url(request):
    request.session.setdefault('fxa_state', generate_fxa_state())
    return fxa_login_url(
        config=settings.FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path=path_with_query(request),
        action='signup')


def default_fxa_login_url(request):
    request.session.setdefault('fxa_state', generate_fxa_state())
    return fxa_login_url(
        config=settings.FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path=path_with_query(request),
        action='signin')


def generate_fxa_state():
    return os.urandom(32).encode('hex')


def redirect_for_login(request):
    return HttpResponseRedirect(default_fxa_login_url(request))


def path_with_query(request):
    next_path = request.path
    qs = request.GET.urlencode()
    if qs:
        return u'{next_path}?{qs}'.format(next_path=next_path, qs=qs)
    else:
        return next_path


def camel_case(snake):
    parts = snake.split('_')
    return parts[0] + ''.join(part.capitalize() for part in parts[1:])


sqs_queue = Queue('amo-account-change-dev', routing_key='default')


class SQSWorker(ConsumerMixin):
    log = getLogger('accounts.sqs')

    def __init__(self, connection):
        self.connection = connection

    def get_consumers(self, Consumer, channel):
        return [Consumer(queues=[sqs_queue],
                         accept=['json'],
                         on_message=self.process_task_on,
                         # callbacks=[self.process_task]
                         )]

    def process_task_on(self, message):
        self.process_task(message.body, message)

    def process_task(self, body, message):
        self.log.info('Got task: %s' % body)
        print message
        try:
            process_fxa_event(body)
        except Exception as ex:
            self.log.exception('Error while processing account events: %s', ex)
        message.ack()

    def on_consume_ready(self, connection, channel, consumers, **kwargs):
        self.log.info('on_consume_ready')
        self.log.info('connection %s' % connection)
        self.log.info('channel %s' % channel)
        self.log.info('consumers %s' % consumers)
        super(SQSWorker, self).on_consume_ready(
            connection, channel, consumers, **kwargs)


class SQSChannel(SQS.Channel):
    """This subclass only exists to encode the message body to base64 because
    Kombu wants to decode it. (Ugh)."""
#    def _message_to_python(self, message, queue_name, queue):
#        print "*** MessageId: %s" % message['MessageId']
#        # print "*** Message: %s" % message
#        message['Body'] = b64encode(message['Body'])
#        # print "*** Message: %s" % message
#        super(SQSChannel, self)._message_to_python(message, queue_name, queue)

    def _message_to_python(self, message, queue_name, queue):
        body = message['Body']
        payload = json.loads(body)
        if queue_name in self._noack_queues:
            queue = self._new_queue(queue_name)
            self.asynsqs.delete_message(queue, message['ReceiptHandle'])
        else:
            try:
                properties = payload['properties']
                delivery_info = payload['properties']['delivery_info']
            except KeyError:
                # json message not sent by kombu?
                delivery_info = {}
                properties = {'delivery_info': delivery_info}
                payload.update({
                    'body': body,
                    'properties': properties,
                })
            # set delivery tag to SQS receipt handle
            delivery_info.update({
                'sqs_message': message, 'sqs_queue': queue,
            })
            properties['delivery_tag'] = message['ReceiptHandle']
        return payload


class SQSTransport(SQS.Transport):
    Channel = SQSChannel


def process_fxa_event(raw_body, **kwargs):
    """Parse and process a single firefox account event."""
    # Try very hard not to error out if there's junk in the queue.
    log = getLogger('accounts.sqs')
    event_type = None
    try:
        body = json.loads(raw_body)
        event = json.loads(body['Message'])
        event_type = event.get('event')
        uid = event.get('uid')
        timestamp = datetime.fromtimestamp(event.get('ts', ''))
        if not (event_type and uid and timestamp):
            raise ValueError(
                'Properties event, uuid, and ts must all be non-empty')
    except (ValueError, KeyError, TypeError), e:
        log.exception('Invalid account message: %s' % e)
    else:
        if event_type == 'primaryEmailChanged':
            email = event.get('email')
            if not email:
                log.error('Email property must be non-empty for "%s" event' %
                          event_type)
            else:
                primary_email_change_event.delay(email, uid, timestamp)
        else:
            log.debug('Dropping unknown event type %r', event_type)


def process_sqs_queue(queue_url, aws_region, queue_wait_time):
    connection_kwargs = {'userid': settings.AWS_ACCESS_KEY_ID,
                         'password': settings.AWS_SECRET_ACCESS_KEY,
                         'connect_timeout': queue_wait_time,
                         'transport': SQSTransport,
                         'transport_options': {'region': aws_region}}
    with Connection(queue_url, **connection_kwargs) as conn:
        try:
            worker = SQSWorker(conn)
            worker.run()
        except KeyboardInterrupt:
            pass
