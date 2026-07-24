"""Load GitHub/Gitea workflow YAML without YAML 1.1's ``on`` coercion."""

from __future__ import annotations

import pathlib
import re

import yaml
from yaml.constructor import ConstructorError


class _WorkflowLoader(yaml.SafeLoader):
    def construct_mapping(
        self,
        node: yaml.MappingNode,
        deep: bool = False,
    ) -> dict[object, object]:
        if not isinstance(node, yaml.MappingNode):
            raise ConstructorError(
                None,
                None,
                f"expected a mapping node, got {node.id}",
                node.start_mark,
            )
        self.flatten_mapping(node)
        mapping: dict[object, object] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as exc:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable key",
                    key_node.start_mark,
                ) from exc
            if duplicate:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


_WorkflowLoader.yaml_implicit_resolvers = {
    key: list(value) for key, value in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
for first_character, resolvers in _WorkflowLoader.yaml_implicit_resolvers.items():
    _WorkflowLoader.yaml_implicit_resolvers[first_character] = [
        entry for entry in resolvers if entry[0] != "tag:yaml.org,2002:bool"
    ]
_WorkflowLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)


def load_workflow(path: pathlib.Path) -> dict[object, object]:
    try:
        value = yaml.load(path.read_text(encoding="utf-8"), Loader=_WorkflowLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid workflow YAML: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"workflow root must be a mapping: {path}")
    return value
