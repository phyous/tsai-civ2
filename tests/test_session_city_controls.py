"""City-control dispatch tests with fake Jev replies and synthetic TEST frames."""
from copy import deepcopy
from unittest import mock
import unittest
from civ2.city_controls import city_control_candidates
from test_city_controls import inputs, reviewed
from test_session_planning import session, TestClient, events
from test_session import dialog as basic_dialog
from civ2.policy import dialog_candidates


class CityClient(TestClient):
    def evaluate(self,state,questions):
        result=super().evaluate(state,questions)
        keys=questions['city_action']['criteria']
        result['answers']['city_action']=dict(choice='open_buy_quote',confidence=1.,
            probabilities={key:float(key=='open_buy_quote') for key in keys})
        return result


def setup():
    s=session(False);s.state,screen,s.rules=inputs();s.client=CityClient()
    s.ui.observe.side_effect=[{'sha256':screen['sha256']},{'sha256':'c'*64}]
    s.game.click.return_value=[{'issued':True}]
    return s,screen


@mock.patch('civ2.session.time.sleep')
class SessionCityControlsTests(unittest.TestCase):
    def test_buy_quote_dispatches_only_selected_button_with_real_city_question(self,sleep):
        s,screen=setup();record=reviewed();action,_=s.choose_city_control(screen,record)
        self.assertEqual(action['id'],'open_buy_quote')
        self.assertFalse(action['parameters']['purchase_authorized'])
        s.game.click.assert_called_once_with(540,335);s.ui.key.assert_not_called()
        self.assertEqual(s.pending_decisions,[1]);self.assertEqual(s.decision['receipt'],'dispatched')
        self.assertEqual(s.decision['selected_question'],'city_action')
        self.assertEqual(set(s.client.requests[0]['questions']),{'city_action','empire_strategy'})
        self.assertIn('checkpoint_freshness',s.client.requests[0]['state'])
        event=events(s,'city_control_dispatched')[0]
        self.assertEqual(event['decision'],1);self.assertEqual(event['reviewed'],record)
        self.assertEqual(record['actions'],[])

    def test_forced_exit_has_no_model_call_or_relabelled_old_decision(self,sleep):
        s,screen=setup();s.decision={'id':0,'receipt':'dispatched','action_label':'TEST prior unit choice'}
        prior=deepcopy(s.decision);record=reviewed(['change_production','open_buy_quote'])
        action,_=s.choose_city_control(screen,record)
        self.assertEqual(action['id'],'exit_city');self.assertEqual(s.client.request_count,0)
        self.assertEqual(s.pending_decisions,[]);self.assertEqual(s.decision,prior)
        s.game.click.assert_called_once_with(610,458);s.ui.key.assert_not_called()
        self.assertEqual(len(events(s,'forced_city_control')),1)
        self.assertIsNone(events(s,'city_control_dispatched')[0]['decision'])
        self.assertIsNone(s.history[-1]['decision'])

    def test_image_change_after_city_inference_prevents_click(self,sleep):
        s,screen=setup();s.ui.observe.side_effect=None;s.ui.observe.return_value={'sha256':'c'*64}
        with self.assertRaisesRegex(RuntimeError,'city screen changed'):s.choose_city_control(screen,reviewed())
        s.game.click.assert_not_called();self.assertEqual(s.decision['receipt'],'pending')
        self.assertEqual(events(s,'city_control_dispatched'),[])

    def test_tampered_purchase_authorization_is_not_dispatchable(self,sleep):
        s,screen=setup();action=city_control_candidates(s.state,screen,rules=s.rules)['open_buy_quote']
        action['parameters']['purchase_authorized']=True;s._evaluate=mock.Mock(return_value=action)
        with self.assertRaises(ValueError):s.choose_city_control(screen,reviewed())
        s.ui.observe.assert_not_called();s.game.click.assert_not_called()

    def test_separate_purchase_model_call_receives_actual_quote_not_city_treasury(self,sleep):
        s,screen=setup();d=basic_dialog();d.update(kind='buy_quote',resource_tag='COMPLETE1',
            quote={'item':'TEST Warriors','cost':37,'treasury':49,'purchase_executed':False,'source':'Original TEST quote'})
        action=dialog_candidates(s.state,d)['option_1']
        s._evaluate=mock.Mock(return_value=action)
        s.ui.observe.side_effect=[{'sha256':d['sha256']},{'sha256':'c'*64}]
        s.choose_dialog(d)
        request=s._evaluate.call_args.args[0]
        self.assertEqual(request['state']['mandatory_dialog']['quote'],d['quote'])
        self.assertIsNot(request['state']['mandatory_dialog']['quote'],d['quote'])
        self.assertEqual(s.state['player']['treasury'],50)

    def test_purchase_choice_without_valid_observed_price_stops_before_inference(self,sleep):
        for quote in (None,{'cost':37,'treasury':49},
                      {'cost':True,'treasury':49,'purchase_executed':False}):
            s,_=setup();d=basic_dialog();d.update(kind='buy_quote',resource_tag='COMPLETE1',quote=quote)
            s._evaluate=mock.Mock()
            with self.assertRaisesRegex(RuntimeError,'actual original quote'):s.choose_dialog(d)
            s._evaluate.assert_not_called();s.game.click.assert_not_called()


if __name__=='__main__':unittest.main()
