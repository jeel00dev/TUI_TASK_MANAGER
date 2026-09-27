"""tmux transport, scoped configuration and pane-relative image placement."""
import os
import unittest
from unittest.mock import Mock, patch

from taskcal.chrome import Chrome, command
from taskcal.drawing import Rect
from taskcal.terminal import TmuxTransport


class TmuxGraphicsTests(unittest.TestCase):
    def test_temporarily_enable_only_the_current_pane(self):
        calls=[]
        current=['']
        def run(*args):
            calls.append(args)
            if args[0]=='show-options':
                return current[0]
            if args[0]=='set-option':
                current[0]='' if '-pu' in args else args[-1]
            return ''
        with patch.dict(os.environ,{'TMUX_PANE':'%42'}), patch('taskcal.terminal.tmux',side_effect=run):
            transport=TmuxTransport()
            self.assertEqual('on',current[0])
            transport.close()
            self.assertEqual('',current[0])
        self.assertTrue(all('%42' in c for c in calls))
        self.assertTrue(all('-g' not in c for c in calls))

    def test_preserve_explicit_option_and_user_changes(self):
        for previous in ('off','on','all'):
            current=[previous]
            def run(*args):
                if args[0]=='show-options':return current[0]
                if args[0]=='set-option':current[0]=args[-1]
                return ''
            with patch.dict(os.environ,{'TMUX_PANE':'%1'}), patch('taskcal.terminal.tmux',side_effect=run):
                transport=TmuxTransport()
                transport.close()
                self.assertEqual(previous,current[0])
                transport=TmuxTransport()
                current[0]='off' # An explicit setting made while the app runs.
                transport.close()
                self.assertEqual('off',current[0])

    def test_actual_cell_dimensions_are_used_and_detach_is_tolerated(self):
        with patch.dict(os.environ,{'TMUX_PANE':'%7'}), patch('taskcal.terminal.tmux',return_value='on') as run:
            transport=TmuxTransport()
            run.return_value='10 21'
            self.assertEqual((10,21),transport.metrics())
            run.return_value='0 0'
            self.assertIsNone(transport.metrics())
            run.side_effect=OSError('pane closed')
            self.assertIsNone(transport.metrics())
            transport.close()

    def test_images_follow_native_anchor_instead_of_absolute_client_coordinates(self):
        output=[]
        transport=Mock()
        transport.metrics.return_value=(8,17)
        transport.packet=TmuxTransport.packet
        chrome=Chrome(output.append,transport=transport)
        chrome.add(Rect(12,6,20,8),(49,49,49),(23,23,23),(59,59,59))
        chrome.render()
        data=output[-1]
        placeholder='\U0010eeee\u0305\u0305'.encode()
        self.assertIn(placeholder,data)
        self.assertIn(b'\x1b[38;2;',data)
        self.assertIn(f'P={chrome.anchor},Q=1,H=12,V=6'.encode(),data)
        self.assertNotIn(b'\x1b[7;13H',data) # tmux owns the pane's screen origin.
        self.assertIn(b'\x1bPtmux;\x1b\x1b_G',data)
        chrome.begin()
        chrome.render()
        self.assertIn(b'a=d,d=i',output[-1])
        chrome.close()
        self.assertIn(f'd=I,i={chrome.anchor}'.encode(),output[-1])
        transport.close.assert_called_once()

    def test_passthrough_round_trip_preserves_chunk_boundaries(self):
        payload=command('a=t,i=99,q=2,m=1',b'AAAA')+command('q=2,m=0',b'BBBB')
        encoded=TmuxTransport.packet(payload)
        self.assertEqual(payload,encoded[len(b'\x1bPtmux;'):-2].replace(b'\x1b\x1b',b'\x1b'))
