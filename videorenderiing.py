
import os
import time
import subprocess
import multiprocessing as mp
from pathlib import Path
from typing import List


# 🔹 MUST be top-level for multiprocessing (Windows safe)
def process_segment(segment_path: str, filter_type: str, temp_dir: str) -> str:
    segment_name = Path(segment_path).stem
    output_file = Path(temp_dir) / f"{segment_name}_processed.mp4"

    if filter_type == "grayscale":
        vf_filter = "format=gray"
    elif filter_type == "blur":
        # ✅ STRATEGY 1: More intensive blur filter
        vf_filter = "gblur=sigma=10:steps=4"  # Heavier blur
    elif filter_type == "complex":
        # ✅ STRATEGY 2: Complex filter chain for maximum CPU work
        vf_filter = "format=gray,unsharp=5:5:1.5:5:5:0.0,gblur=sigma=3"
    else:
        raise ValueError("Unknown filter type")

    
    cmd = [
        "ffmpeg",
        "-i", segment_path,
        "-vf", vf_filter,
        "-map", "0:v",
        "-c:v", "libx264",
        "-preset", "medium",          
        "-threads", "1",              
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-y",
        str(output_file)
    ]

    subprocess.run(
        cmd, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.PIPE, 
        check=True
    )

    return str(output_file)


class VideoRenderer:
    def __init__(self, input_video: str):
        self.input_video = input_video
        self.segment_duration = 10  # ✅ FIXED at 10 seconds
        self.temp_dir = Path("temp_segments")
        self.output_dir = Path("output")

        self.temp_dir.mkdir(exist_ok=True)
        self.output_dir.mkdir(exist_ok=True)

    def get_video_duration(self) -> float:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            self.input_video
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())

    def split_video(self) -> List[str]:
        print("📹 Splitting video into 10-second segments...")
        duration = self.get_video_duration()
        num_segments = int(duration / self.segment_duration) + 1
        segments = []

        for i in range(num_segments):
            start = i * self.segment_duration
            out = self.temp_dir / f"segment_{i:03d}.mp4"

            cmd = [
                "ffmpeg",
                "-ss", str(start),
                "-i", self.input_video,
                "-t", str(self.segment_duration),
                "-map", "0:v",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                "-y",
                str(out)
            ]

            subprocess.run(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                check=True
            )
            
            if out.exists() and out.stat().st_size > 0:
                segments.append(str(out))

        print(f"✅ Created {len(segments)} segments")
        return segments

    def apply_filter_sequential(self, segments: List[str], filter_type: str):
        print(f"\n⏳ Sequential Processing ({len(segments)} segments, single-threaded)...")
        start = time.time()

        processed = []
        for i, s in enumerate(segments, 1):
            print(f"  Processing segment {i}/{len(segments)}...", end="\r")
            processed.append(process_segment(s, filter_type, str(self.temp_dir)))

        elapsed = time.time() - start
        print(f"\n✅ Sequential completed: {elapsed:.2f}s")
        return processed, elapsed

    def apply_filter_parallel(self, segments: List[str], filter_type: str):
        num_cores = mp.cpu_count()
        
        # ✅ STRATEGY 4: Limit pool size to actual segments or cores
        pool_size = min(num_cores, len(segments))
        
        print(f"\n🚀 Parallel Processing ({len(segments)} segments, {pool_size} workers)...")
        start = time.time()

        args = [(s, filter_type, str(self.temp_dir)) for s in segments]
        
        with mp.Pool(pool_size) as pool:
            processed = pool.starmap(process_segment, args)

        elapsed = time.time() - start
        print(f"✅ Parallel completed: {elapsed:.2f}s")
        return processed, elapsed

    def merge_segments(self, segments: List[str], output_name: str):
        print(f"🔗 Merging segments into {output_name}...")
        concat_file = self.temp_dir / "concat.txt"
        
        with open(concat_file, "w") as f:
            for s in segments:
                abs_path = os.path.abspath(s).replace("\\", "/")
                f.write(f"file '{abs_path}'\n")

        output_file = self.output_dir / output_name
        cmd = [
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            "-y",
            str(output_file)
        ]

        subprocess.run(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            check=True
        )
        print(f"✅ Saved: {output_file}")
        return str(output_file)

    def display_performance(self, seq, par):
        speedup = seq / par if par > 0 else 0
        efficiency = (speedup / mp.cpu_count()) * 100
        time_saved = seq - par
        
        print("\n" + "=" * 70)
        print("📊 PERFORMANCE COMPARISON (10s SEGMENTS)")
        print("=" * 70)
        print(f"Sequential Time       : {seq:.2f}s")
        print(f"Parallel Time         : {par:.2f}s")
        print(f"Time Saved            : {time_saved:.2f}s ({(time_saved/seq)*100:.1f}%)")
        print(f"Speedup               : {speedup:.2f}x")
        print(f"CPU Cores Available   : {mp.cpu_count()}")
        print(f"Parallel Efficiency   : {efficiency:.1f}%")
        print(f"Time per segment (seq): {seq/len(segments) if segments else 0:.2f}s")
        print(f"Time per segment (par): {par/len(segments) if segments else 0:.2f}s")
        print("=" * 70)
        
        if speedup >= 4:
            print(f"\n🎉 Excellent! {speedup:.1f}x faster with parallel processing!")
        elif speedup >= 2:
            print(f"\n✅ Good speedup of {speedup:.1f}x achieved")
        elif speedup >= 1.5:
            print(f"\n✓ Decent speedup of {speedup:.1f}x")
        else:
            print(f"\n⚠️  Low speedup of {speedup:.1f}x - try different filter type")

    def cleanup(self):
        print("\n🧹 Cleaning up temporary files...")
        count = 0
        for f in self.temp_dir.glob("*"):
            try:
                f.unlink()
                count += 1
            except:
                pass
        
        try:
            self.temp_dir.rmdir()
            print(f"✅ Removed {count} temporary files")
        except:
            pass


def main():
    input_video = "hackathonvideo1.mp4"
    
    # ✅ CHOOSE YOUR STRATEGY:
    # "grayscale" - simple conversion
    # "blur" - heavier blur filter (sigma=10, steps=4)
    # "complex" - multiple filters chained together
    filter_type = "blur"  # <-- Try changing this to "complex" for even more work

    if not os.path.exists(input_video):
        print(f"❌ Error: {input_video} not found")
        print(f"   Current directory: {os.getcwd()}")
        return

    # Show video info
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", input_video]
        result = subprocess.run(cmd, capture_output=True, text=True)
        total_duration = float(result.stdout.strip())
        expected_segments = int(total_duration / 10) + 1
        
        print("=" * 70)
        print("🎬 VIDEO PROCESSING SETUP")
        print("=" * 70)
        print(f"Input Video       : {input_video}")
        print(f"Total Duration    : {total_duration:.1f}s")
        print(f"Filter Type       : {filter_type}")
        print(f"Segment Duration  : 10 seconds (mandatory)")
        print(f"Expected Segments : ~{expected_segments}")
        print(f"Encoding Preset   : medium")
        print(f"Threading Mode    : 1 thread per process (no competition)")
        print(f"CPU Cores         : {mp.cpu_count()}")
        print("=" * 70)
        print()
        
    except Exception as e:
        print(f"⚠️  Could not read video info: {e}\n")

    renderer = VideoRenderer(input_video)
    global segments  # For display_performance
    segments = []

    try:
        # Split video
        segments = renderer.split_video()
        
        if len(segments) < 4:
            print("\n⚠️  Warning: Very short video - parallel gains may be minimal")

        # Sequential processing
        seq_out, seq_time = renderer.apply_filter_sequential(segments, filter_type)
        renderer.merge_segments(seq_out, "output_sequential.mp4")

        # Parallel processing  
        par_out, par_time = renderer.apply_filter_parallel(segments, filter_type)
        renderer.merge_segments(par_out, "output_parallel.mp4")

        # Show performance comparison
        renderer.display_performance(seq_time, par_time)

    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        renderer.cleanup()

if __name__ == "__main__":
    mp.freeze_support()
    main()
