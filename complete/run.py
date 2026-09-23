"""Launch the complete site. python run.py [--demo] [--port 8001]."""
import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='EKT: frontend and FastAPI in one server')
    parser.add_argument('--demo', action='store_true', help='Synthetic catalog and offline replies on port 8002')
    parser.add_argument('--port', type=int, help='Local port (default 8001; demo 8002)')
    args = parser.parse_args()
    port = args.port if args.port is not None else (8002 if args.demo else 8001)
    if not 1 <= port <= 65535:
        parser.error('--port must be between 1 and 65535')
    os.chdir(Path(__file__).resolve().parent)
    os.environ['CATALOG_MODE'] = 'demo' if args.demo else 'normalized'
    if args.demo:
        os.environ['AI_PROVIDER'] = 'demo'
    import uvicorn
    print(f'EKT site: http://127.0.0.1:{port}/', flush=True)
    uvicorn.run('app.main:app', host='127.0.0.1', port=port)


if __name__ == '__main__':
    main()
