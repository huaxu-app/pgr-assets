import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
from pgr_assets.commands.root import Args

logger = logging.getLogger('pgr-assets')

def main() -> None:
    args = Args().parse_args()
    args.func(args)

if __name__ == '__main__':
    main()
