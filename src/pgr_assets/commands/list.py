from .helpers import build_source_set, BaseArgs


class ListCommand(BaseArgs):
    def configure(self) -> None:
        self.set_defaults(func=list_cmd)


def list_cmd(args: ListCommand):
    ss = build_source_set(args)

    for bundle in ss.list_all_bundles():
        print(bundle)
