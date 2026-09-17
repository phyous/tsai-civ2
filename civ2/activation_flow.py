"""Finite ordinary-input continuation of one actual model activation intent.

The caller persists the returned pending dictionary and supplies its journal's
append function. This module has no Session, model-client or checkpoint writer.
It deliberately leaves uncertain inputs pending instead of replaying them.
"""
from copy import deepcopy
import time

from .revision import prefixed_revision
from .unit_activation import (UnitActivationError, validate_activation,
    activation_popup, activation_radio_proof, activation_result)


def begin_activation(action, state, observation, rules, decision, emit,
                     reviewed=None, *, ready=False):
    if type(decision) is not int or decision < 1:
        raise UnitActivationError('A real model decision is required')
    validate_activation(action,state,observation,rules,reviewed,ready=ready)
    pending=dict(decision=decision,action=deepcopy(action),before_state=deepcopy(state),
                 phase='inspect_unit',last_input=None)
    emit('unit_activation_started',decision=decision,action=deepcopy(action),
         before_revision=prefixed_revision(state),source_image_sha256=observation['sha256'])
    return pending


def activation_step(pending, observation, game_text, labels_text):
    """Return the sole currently authorized step, never execute it."""
    action=pending['action'];phase=pending['phase']
    if phase=='inspect_unit':
        if observation.get('sha256')!=action['preconditions']['image_sha256']:
            raise UnitActivationError('City image changed before unit inspection')
        return dict(kind='click',point=deepcopy(action['parameters']['center']),
                    source_image_sha256=observation['sha256'])
    if phase not in ('select_activation','confirm_activation'):
        raise UnitActivationError('Activation is awaiting readback or has an uncertain input')
    proof=activation_popup(action,observation,game_text,labels_text)
    command=dict(kind='click',point=deepcopy(proof['option']['center']),
                 source_image_sha256=observation['sha256'],popup=proof)
    if phase=='confirm_activation':
        radio=activation_radio_proof(action,observation,game_text,labels_text)
        command=dict(kind='key',code='Enter',source_image_sha256=observation['sha256'],
                     popup=proof,radio=radio)
    return command


def dispatch_activation_step(pending, ui, observation, game_text, labels_text, emit):
    """Send at most one bounded native input, retaining failures for audit.

Every click is followed by observed pointer parking and a fresh image. The next
call must independently validate its popup/radio. No default Enter is possible.
"""
    command=activation_step(pending,observation,game_text,labels_text)
    current=ui.observe()
    if current['sha256']!=command['source_image_sha256']:
        raise UnitActivationError('Original screen changed before activation input')
    # Revalidate the source control against the actual immediate capture.
    if activation_step(pending,current,game_text,labels_text)!=command:
        raise UnitActivationError('Activation source control changed before input')
    step=pending['phase'];decision=pending['decision'];inputs=[];parking=None;stage='resume'
    emit('unit_activation_step_started',decision=decision,step=step,command=deepcopy(command))
    pending['phase']='input_uncertain'
    pending['last_input']=dict(step=step,command=deepcopy(command),inputs=inputs)
    try:
        ui.game.rpc('resume')
        if command['kind']=='click':
            stage='click'
            inputs=ui.game.click(*command['point'])
            pending['last_input']['inputs']=deepcopy(inputs)
            time.sleep(.2)
            stage='pointer_park'
            parking=ui.park_pointer()
            pending['last_input']['pointer_park']=deepcopy(parking)
        else:
            stage='key'
            inputs=ui.key('Enter',settle=.25)
            pending['last_input']['inputs']=deepcopy(inputs)
        stage='capture'
        after=ui.observe()
        emit('unit_activation_step_dispatched',decision=decision,step=step,command=deepcopy(command),
             before=current['sha256'],after=after['sha256'],inputs=deepcopy(inputs),pointer_park=parking)
        pending['phase']={'inspect_unit':'select_activation','select_activation':'confirm_activation',
                          'confirm_activation':'checkpoint'}[step]
        return after
    except BaseException as error:
        # A failed mouse helper can still contain ordinary motion receipts.
        partial=getattr(error,'cursor_receipt',None)
        if partial is not None:
            if stage=='pointer_park':parking=deepcopy(partial)
            elif not inputs:inputs=[deepcopy(partial)]
        pending['last_input']['pointer_park']=deepcopy(parking)
        pending['last_input']['inputs']=deepcopy(inputs)
        emit('unit_activation_failed',decision=decision,step=step,reason=str(error),
             inputs=deepcopy(inputs),pointer_park=deepcopy(parking),success_not_inferred=True)
        raise
    finally:
        ui.game.rpc('pause')


def complete_activation(pending, after_state, checkpoint, emit):
    """Record only a supplied real checkpoint; never fabricate an observation."""
    if pending.get('phase')!='checkpoint' or type(checkpoint) is not int or checkpoint<1:
        raise UnitActivationError('Activation requires its completed input and native checkpoint')
    result=activation_result(pending['action'],pending['before_state'],after_state)
    emit('unit_activation_observed',decision=pending['decision'],checkpoint=checkpoint,result=result)
    pending['phase']='complete' if result['status']!='unexpected_change' else 'failed_readback'
    return result
