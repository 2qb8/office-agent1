from pathlib import Path
import mss


def screenshot(output_path: str, monitor: int = 1):
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with mss.MSS() as sct:
        monitor_info = sct.monitors[monitor]
        image = sct.grab(monitor_info)
        sct.shot(mon=monitor, output=str(output))

    return {
        "success": output.exists(),
        "path": str(output),
        "width": image.width,
        "height": image.height,
    }


if __name__ == "__main__":
    print(screenshot("output/test_screenshot.png"))