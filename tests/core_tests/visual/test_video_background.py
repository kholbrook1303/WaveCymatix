import unittest
from unittest.mock import Mock

from wavecymatix.core.visual.VideoBackground import VideoBackground


class VideoBackgroundTests(unittest.TestCase):
    def test_applied_videos_select_first_path_without_shuffle(self):
        video = object.__new__(VideoBackground)
        video.randomize = True
        video.video_directory = "videos"

        video._apply_videos(["one.mp4", "two.webm"], shuffle=False)

        self.assertEqual(video.videos, ["one.mp4", "two.webm"])
        self.assertEqual(video.current_video_index, 0)
        self.assertEqual(video.current_video_path, "one.mp4")

    def test_empty_video_list_clears_current_path(self):
        video = object.__new__(VideoBackground)
        video.randomize = False
        video.video_directory = "videos"
        video.current_video_path = "old.mp4"

        video._apply_videos([])

        self.assertEqual(video.videos, [])
        self.assertIsNone(video.current_video_path)


if __name__ == "__main__":
    unittest.main()
