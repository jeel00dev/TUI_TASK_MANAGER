"""Pixel geometry, terminal lifecycle, and native input under rounded chrome."""
import base64
import re
import struct
import unittest
import zlib
from unittest.mock import Mock, patch

from taskcal.chrome import Chrome, contour, inside_tmux, radius_for, supported
from taskcal.drawing import Rect
from test_terminal import Screen
from test_visual_calendar import VisualFixture


FILL, OUTER, EDGE, BLUE = (49,49,49), (23,23,23), (59,59,59), (64,153,255)


def pixel(rows,x,y):
    return tuple(rows[y][x*4:x*4+4])


def pngs(output):
    """Decode the actual transmitted PNG, independently of the rasterizer."""
    payload = bytearray()
    result = []
    for match in re.finditer(rb'\x1b_G([^;]*);(.*?)\x1b\\',output):
        params, data = match.groups()
        if not data:
            continue
        payload.extend(data)
        if b'm=0' not in params:
            continue
        png = base64.b64decode(payload)
        payload.clear()
        assert png.startswith(b'\x89PNG\r\n\x1a\n')
        offset, compressed = 8, bytearray()
        while offset < len(png):
            length = struct.unpack('!I',png[offset:offset+4])[0]
            kind, data = png[offset+4:offset+8], png[offset+8:offset+8+length]
            if kind == b'IHDR':
                width,height = struct.unpack('!II',data[:8])
            if kind == b'IDAT':
                compressed.extend(data)
            offset += 12+length
        raw = zlib.decompress(compressed)
        stride = 1+4*width
        result.append((width,height,[raw[y*stride+1:(y+1)*stride] for y in range(height)]))
    return result


class ChromeTests(unittest.TestCase):
    def test_large_circular_corner_and_clear_center(self):
        rows=contour(100,80,18,FILL,OUTER,EDGE)
        self.assertEqual(OUTER+(255,),pixel(rows,0,8))
        self.assertEqual(EDGE+(255,),pixel(rows,50,0))
        self.assertEqual((0,0,0,0),pixel(rows,50,40))
        self.assertEqual((0,0,0,0),pixel(rows,8,8))
        # Antialiased pixels at the curve, not a one-cell diagonal chamfer.
        corner={pixel(rows,x,y) for y in range(18) for x in range(18)}
        self.assertGreater(len(corner),10)
        for y in range(80):
            self.assertEqual(400,len(rows[y]))
            for x in range(50):
                self.assertEqual(pixel(rows,x,y),pixel(rows,99-x,y))
                self.assertEqual(pixel(rows,x,y),pixel(rows,x,79-y))

    def test_capsules_scale_and_never_overlap(self):
        self.assertEqual(8.5,radius_for('pill',96,17,17))
        self.assertEqual(25.5,radius_for('pill',96,51,17))
        self.assertEqual(6,radius_for('panel',12,100,17))
        self.assertAlmostEqual(2*radius_for('panel',200,200,17),radius_for('panel',400,400,34))
        for width,height in ((24,17),(72,51),(300,600),(9,3),(1,1)):
            radius=radius_for('pill',width,height,17)
            rows=contour(width,height,radius,FILL,OUTER,EDGE)
            self.assertEqual(height,len(rows))
            self.assertTrue(all(len(r)==width*4 for r in rows))

    def test_task_accent_is_four_pixels_and_stays_inside_curve(self):
        rows=contour(100,80,15,FILL,OUTER,EDGE,accent=BLUE,accent_height=4)
        for y in range(76,80):
            self.assertEqual(BLUE+(255,),pixel(rows,50,y))
        self.assertEqual((0,0,0,0),pixel(rows,50,75))
        self.assertEqual(OUTER+(255,),pixel(rows,0,79))

    def test_modal_occludes_old_border_and_png_is_valid(self):
        output=[]
        renderer=Chrome(output.append,lambda:(8,17))
        renderer.add(Rect(0,0,20,10),FILL,OUTER,EDGE)
        renderer.add(Rect(5,0,8,5),FILL,OUTER,EDGE)
        renderer.render()
        width,height,rows=pngs(output[-1])[0]
        self.assertEqual((160,170),(width,height))
        self.assertEqual((0,0,0,0),pixel(rows,50,0))
        self.assertEqual(EDGE+(255,),pixel(rows,30,0))
        # Masking one row must not mutate cached, otherwise equal rows.
        self.assertNotEqual(pixel(rows,50,0),pixel(rows,50,169))
        self.assertTrue(all(b'q=2' in p for p in re.findall(rb'\x1b_G([^;]*);',output[-1])))
        self.assertIn(b'C=1,z=-1',output[-1])

    def test_screen_clear_resize_and_exit_do_not_leave_images(self):
        output=[]
        size=[(8,17)]
        renderer=Chrome(output.append,lambda:size[0])
        def frame():
            renderer.begin()
            renderer.add(Rect(1,1,10,3),FILL,OUTER,EDGE,'pill')
            renderer.add(Rect(15,1,10,3),FILL,OUTER,EDGE,'pill')
            renderer.render()
        frame()
        first_ids={i for i,_ in renderer.placements}
        self.assertEqual(1,len(pngs(output[-1]))) # shared texture, two placements
        frame() # A clear may have evicted Kitty's images; re-upload cached PNG.
        self.assertEqual(1,len(pngs(output[-1])))
        self.assertEqual(first_ids,{i for i,_ in renderer.placements})
        size[0]=(10,21)
        frame()
        self.assertEqual((100,63),pngs(output[-1])[0][:2])
        self.assertTrue(first_ids.isdisjoint(i for i,_ in renderer.placements))
        renderer.begin()
        renderer.render() # minimum-size message removes placements
        self.assertIn(b'a=d,d=i',output[-1])
        self.assertFalse(renderer.placements)
        renderer.close()
        self.assertIn(b'a=d,d=I',output[-1])
        self.assertFalse(renderer.cache)
        self.assertNotIn(b'a=d,d=A',b''.join(output))

    def test_only_real_direct_kitty_enables_images(self):
        with patch.dict('os.environ',{'KITTY_WINDOW_ID':'1','TERM':'xterm-kitty'},clear=True), patch('os.isatty',return_value=True), patch('taskcal.chrome.cell_size',return_value=(8,17)), patch('taskcal.chrome.inside_tmux',return_value=False):
            self.assertTrue(supported())
            with patch.dict('os.environ',{'NO_COLOR':'1'}):
                self.assertFalse(supported())
            with patch('taskcal.chrome.inside_tmux',return_value=True):
                self.assertFalse(supported())
            with patch.dict('os.environ',{'TERM':'screen-256color'}):
                self.assertFalse(supported())

    def test_tmux_uses_own_pane_and_detects_inherited_environment(self):
        with patch.dict('os.environ',{'TMUX':'/tmp/test','TMUX_PANE':'%42'}), patch('os.ttyname',return_value='/dev/pts/42'), patch('subprocess.run',return_value=Mock(returncode=0,stdout='/dev/pts/42\n')) as run:
            self.assertTrue(inside_tmux())
            self.assertIn('%42',run.call_args.args[0])
            with patch('os.ttyname',return_value='/dev/pts/99'):
                self.assertFalse(inside_tmux())


class RoundedAppTests(VisualFixture):
    def setUp(self):
        super().setUp()
        stubs={name:Mock(return_value=value) for name,value in {
            'has_colors':True,'start_color':None,'use_default_colors':None,
            'can_change_color':True,'color_content':(0,0,0),'init_color':None,
            'init_pair':None,'color_pair':0}.items()}
        with patch.dict('os.environ',{},clear=True), patch.multiple('curses',**stubs,COLORS=256,COLOR_PAIRS=256,create=True):
            self.app.theme.install()
        self.app.paint.chrome=Chrome(lambda data:None,lambda:(8,17))

    def test_every_view_mouse_and_minute_rule_with_graphics(self):
        self.add('Rounded task')
        for view in ('day','week','month','year','inbox','history','search'):
            self.app.view=view
            self.refresh()
            self.assertTrue(self.app.paint.chrome.surfaces)
            if view in ('day','week'):
                cells=self.app.paint.cells
                marker=next(xy for xy,(char,style) in cells.items() if char=='●' and style=='red')
                main=next(r for r,action,_ in self.app.views.hits if action=='scroll')
                for x in range(main.x+7,main.x+main.w-1):
                    self.assertIn(cells[(x,marker[1])][0],('┄','●'))
        self.app.view='week'
        self.refresh()
        rect=next(r for r,a,v in self.app.views.hits if a=='task')
        self.app.mouse((rect.x+1,rect.y+1,'click',False))
        self.assertEqual('Rounded task',self.app.chosen().task.title)
        self.app.screen=self.app.paint.screen=Screen(15,50)
        self.app.draw()
        self.assertFalse(self.app.paint.chrome.placements)
        self.assertFalse(self.app.views.hits)

    def test_repeated_modal_redraws_do_not_accumulate_surfaces(self):
        self.add()
        self.refresh()
        self.app.modal('EDIT TASK',70,24)
        count=len(self.app.paint.chrome.surfaces)
        for _ in range(10):
            self.app.modal('EDIT TASK',70,24)
            self.assertEqual(count,len(self.app.paint.chrome.surfaces))
        self.app.draw()
        self.assertLess(len(self.app.paint.chrome.surfaces),count)
