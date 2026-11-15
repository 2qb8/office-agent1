#!/usr/bin/env bash
#
# Run the tests that need Tk and a display, without a display.
#
#   scripts/gui-tests.sh                  xvfb-run here, or the container
#   scripts/gui-tests.sh --docker         always the container
#   scripts/gui-tests.sh --no-docker      never the container (used inside it)
#   scripts/gui-tests.sh --shot out.png   also render the window to a file
#
# Set GUI_TESTS_PYTHON to choose the interpreter (the container points it at
# its own venv) and GUI_TESTS_SKIP_SUITE=1 to render only the screenshot.
#
# Without a display the window tests skip, which is how GUI defects reached
# CI before anyone saw them on their own machine. This script sets
# OFFICE_AGENT_REQUIRE_GUI=1, so those skips become failures: no Tk, no
# display and no window means a red run, not a quiet one.

set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"

mode=auto
shot=

while [ $# -gt 0 ]; do
    case $1 in
        --docker) mode=docker ;;
        --no-docker) mode=local ;;
        --shot)
            shift
            if [ $# -eq 0 ]; then
                echo "--shot needs a path, for example docs/window-local.png" >&2
                exit 2
            fi
            shot=$1
            ;;
        -h | --help)
            sed -n '3,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "Unknown option: $1 (try --help)" >&2
            exit 2
            ;;
    esac
    shift
done

# The CI runner's screen, so a local render is roughly the same size.
screen=1024x768x24

python_bin() {
    if [ -n "${GUI_TESTS_PYTHON:-}" ]; then
        echo "$GUI_TESTS_PYTHON"
    elif [ -x .venv/bin/python ]; then
        echo .venv/bin/python
    else
        echo python3
    fi
}

run_local() {
    local python
    python=$(python_bin)

    if ! "$python" -c "import tkinter" >/dev/null 2>&1; then
        echo "tkinter is not installed for $python." >&2
        echo "  Debian/Ubuntu: sudo apt-get install -y python3-tk xvfb" >&2
        echo "  Fedora:        sudo dnf install -y python3-tkinter xorg-x11-server-Xvfb" >&2
        echo "Then run this script again, or let it use Docker: --docker" >&2
        return 1
    fi

    local runner=()

    if [ -z "${DISPLAY:-}" ]; then
        if ! command -v xvfb-run >/dev/null 2>&1; then
            echo "There is no DISPLAY and no xvfb-run installed." >&2
            echo "  Debian/Ubuntu: sudo apt-get install -y xvfb" >&2
            echo "Or run the tests in the container: --docker" >&2
            return 1
        fi

        runner=(xvfb-run -a -s "-screen 0 $screen")
    fi

    # GUI_TESTS_SKIP_SUITE=1 runs only the screenshot, for a caller that has
    # already run the suite (Linux CI renders the picture afterwards).
    if [ "${GUI_TESTS_SKIP_SUITE:-}" = "1" ] && [ -n "$shot" ]; then
        :
    else
        OFFICE_AGENT_REQUIRE_GUI=1 \
            ${runner[@]+"${runner[@]}"} \
            "$python" -m unittest discover -s tests -v
    fi

    if [ -n "$shot" ]; then
        OFFICE_AGENT_REQUIRE_GUI=1 \
            ${runner[@]+"${runner[@]}"} \
            "$python" assets/window_shot.py "$shot"
    fi
}

run_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        echo "docker is not installed; install python3-tk and xvfb instead." >&2
        return 1
    fi

    if ! docker info >/dev/null 2>&1; then
        echo "Docker is installed but its daemon is not reachable." >&2
        echo "Start Docker, or install python3-tk and xvfb to run the tests directly." >&2
        return 1
    fi

    local image=office-agent-gui-tests
    local pass=()

    if [ -n "$shot" ]; then
        pass=(--shot "$shot")
    fi

    echo "Building $image (the first run does this once)..."

    docker build -f docker/gui-tests.Dockerfile -t "$image" .

    # The image carries its own interpreter with Tk and the requirements;
    # the checkout is mounted so the tests see the working tree.
    docker run --rm \
        -v "$root:/app" \
        -w /app \
        -u "$(id -u):$(id -g)" \
        -e HOME=/tmp \
        -e GUI_TESTS_PYTHON=/opt/venv/bin/python \
        -e GUI_TESTS_SKIP_SUITE \
        "$image" \
        bash scripts/gui-tests.sh --no-docker ${pass[@]+"${pass[@]}"}
}

case $mode in
    docker) run_docker ;;
    local) run_local ;;
    auto)
        if [ -n "${DISPLAY:-}" ] || command -v xvfb-run >/dev/null 2>&1; then
            run_local
        else
            echo "No display and no xvfb-run: using the container." >&2
            run_docker
        fi
        ;;
esac
