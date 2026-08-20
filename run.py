import multiprocessing
import sys


def _arg_value(name, default=None):
    if name not in sys.argv:
        return default
    i=sys.argv.index(name)
    return sys.argv[i+1] if i+1 < len(sys.argv) else default


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if "--self-test-artwork" in sys.argv:
        from label_tool.self_test import run_artwork_self_test
        out=_arg_value("--self-test-output", "artwork_self_test.json")
        raise SystemExit(run_artwork_self_test(out))
    if "--self-test-ocr" in sys.argv:
        from label_tool.self_test import run_ocr_self_test
        out=_arg_value("--self-test-output", "ocr_self_test.json")
        raise SystemExit(run_ocr_self_test(out))
    from label_tool.app import main
    main()
