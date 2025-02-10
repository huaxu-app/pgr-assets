import logging

import cmd.root

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('pgr-assets')


if __name__ == '__main__':
    args = cmd.root.Args().parse_args()
    args.func(args)
