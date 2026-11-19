import unittest
from pathlib import Path
import tempfile
from stageplay_core import (media_kind, next_index, crop_transform, default_settings,
                            normalized_settings, resolve_saved_path, media_path_for_save)


class StagePlayCoreTests(unittest.TestCase):
    def test_types(self):
        self.assertEqual(media_kind('a.MOV'), 'video')
        self.assertEqual(media_kind('a.PDF'), 'pdf')
        self.assertEqual(media_kind('a.JPG'), 'image')
        self.assertIsNone(media_kind('a.PPTX'))

    def test_loops(self):
        self.assertEqual(next_index(1, 3, 'ONE', False), 1)
        self.assertEqual(next_index(2, 3, 'ALL', False), 0)
        self.assertIsNone(next_index(2, 3, 'OFF', True))
        self.assertIsNone(next_index(1, 3, 'OFF', False))
        self.assertEqual(next_index(1, 3, 'OFF', True), 2)

    def test_fit_fill_zoom_and_crop(self):
        s = default_settings()
        rect = crop_transform((1920,1080), (1000,1000), s)
        self.assertAlmostEqual(rect['effective'][2],1000)
        self.assertAlmostEqual(rect['effective'][3],562.5)
        s['mode']='FILL'
        rect=crop_transform((1920,1080), (1000,1000), s)
        self.assertAlmostEqual(rect['effective'][3],1000)
        self.assertGreater(rect['effective'][2],1000)
        s['zoom']=2.0
        zoomed=crop_transform((1920,1080), (1000,1000), s)
        self.assertAlmostEqual(zoomed['effective'][3],2000)
        s['crop_l']=20
        cropped=crop_transform((1920,1080), (1000,1000), s)
        self.assertNotEqual(cropped['full'][0], zoomed['full'][0])

    def test_clamps(self):
        s=normalized_settings(dict(zoom=900, crop_l=99, volume=-10))
        self.assertEqual(s['zoom'],4)
        self.assertEqual(s['crop_l'],45)
        self.assertEqual(s['volume'],0)

    def test_relative_paths(self):
        with tempfile.TemporaryDirectory() as t:
            show=str(Path(t)/'show.json')
            media=str(Path(t)/'media'/'sample.mp4')
            self.assertEqual(resolve_saved_path(media_path_for_save(media,show),show), media)

if __name__=='__main__': unittest.main()
