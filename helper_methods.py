import re
from itertools import takewhile


class Subgraph:
    key = None
    point = None
    nodes: {}
    children: {}

    def __init__(self, key, nodes={}, children={}):
        self.key = key
        self.nodes = nodes
        self.children = children

    def render_attrs(self):
        return dict_to_attrs({"style": "invix", "label": 'cluster_' + self.key}, ';')

    def render_point(self):
        return "{key}[{attrs}]".format(
            key=self.key, attrs=dict_to_attrs({"style": "invix", "shape": "rarrow"})
        )

    def render_nodes(self):
        return ';'.join(['"{}"'.format(node_key) for node_key in self.nodes.keys()])

    def render_children(self):
        return '\n'.join([child.render() for child in self.children.values()])

    def render(self):
        return """
            subgraph cluster_{key} {{
            {attrs}
            {point}
            {children}
            }}""".format(
            key=self.key,
            attrs=self.render_attrs(),
            point=self.render_point(),
            children=self.render_nodes() + self.render_children(),
        )


class CardSubgraph(Subgraph):
    def render(self):
        return """
            subgraph cluster_{key} {{
            {attrs}
            {children}
            }}""".format(
            key=self.key,
            attrs=self.render_attrs(),
            children=self.render_nodes() + self.render_children(),
        )


class StateSubgraph(Subgraph):
    def render(self):
        return """
            subgraph cluster_{key} {{
            {attrs}
            {point}
            {children}
            }}""".format(
            key=self.key,
            attrs=self.render_attrs(),
            point=self.render_point(),
            children=self.render_nodes() + self.render_children(),
        )


class Point:
    def attrs(self):
        return {"style": "invis", "shape": "point"}


class Node:
    key = None


def snake_case(k):
    return re.sub(r"[^\w]+", "_", k).lower()


def dict_to_attrs(dict, delimiter=","):
    return delimiter.join(
        [
            (('{}="{}"', "{}={}")[k == "label" and v.startswith("<<")]).format(k, v)
            for k, v in dict.items()
            if k != "name"
        ]
    )


def create_node_key(issue_key):
    return '"{}"'.format(issue_key)


def graphviz_node_string(node_key, node_attributes):
    return '"{}" [{}]'.format(node_key, dict_to_attrs(node_attributes))


def create_edge_text(source_node_text, destination_node_text, edge_options={}):
    edge = '{}->{}[{}]'.format(
        source_node_text,
        destination_node_text,
        dict_to_attrs(edge_options))
    return edge


def invert_dict(d):
    inverse = dict()
    for key in d:
        # Go through the list that is saved in the dict:
        l = d[key] if isinstance(d[key], list) else d[key].split()
        for item in l:
            # Check if in the inverted dict the key exists
            if item not in inverse:
                # If not create a new list
                inverse[item] = [key]
            else:
                inverse[item].append(key)
    return inverse

def path_to_root(node, key):
    for k_name, k_tree in node.items():
        if k_name == key:
            if len(k_tree):
                return [snake_case(k_name)]
            else:
                return True
        else:
            result = path_to_root(k_tree, key)
            if result:
                if result == True:
                    return [snake_case(k_name)]
                else:
                    return [snake_case(k_name)] + result

def common_path(node, keys):

    if not isinstance(keys, list):
        raise Exception("keys must be a list")
    paths = [path_to_root(node, key) for key in keys]
    print(f'paths: {paths}')
    try:
        common_path_arr = [
            c[0] for c in takewhile(lambda x: all(x[0] == y for y in x), zip(*paths))
        ]
    except TypeError:
        common_path_arr = []

    return common_path_arr


def graft_subgraph_tree_branches(subgraph_tree):
    grafts = []
    for parent_key, child_states in subgraph_tree.items():
        for child_state, child_keys in child_states.items():
            for child_key in child_keys:
                if child_key in subgraph_tree.keys():
                    grafts.append(
                        {
                            "parent_key": parent_key,
                            "child_state": child_state,
                            "child_key": child_key,
                        }
                    )

    for graft in grafts:
        subgraph_tree[graft["parent_key"]][graft["child_state"]][
            graft["child_key"]
        ] = subgraph_tree.pop(graft["child_key"])


def cluster_tree(tree):
    cluster_style = ""
    cluster_point_style = ""
    c_tree = {}
    for node_name, child_groups in tree.items():
        if len(child_groups) == 0:
            if node_name:
                c_tree[node_name] = {}
            continue
        node_cluster_name = snake_case("cluster_" + node_name)
        c_tree[node_cluster_name] = {}
        if node_name:
            c_tree[node_cluster_name][node_name] = {}
        for child_group_name, child_group in child_groups.items():
            child_cluster_name = snake_case(
                "cluster_" + node_name + "_" + child_group_name
            )
            c_tree[node_cluster_name][child_cluster_name] = cluster_tree(child_group)
    return c_tree


def cluster_shrub_1(tree, root=True):
    cluster_style = ""
    cluster_point_style = ""
    c_tree = {}
    for node_name, child_groups in tree.items():
        if len(child_groups) == 0:
            if not root:
                c_tree[node_name] = {}
            continue
        node_cluster_name = snake_case("cluster_" + node_name)
        c_tree[node_cluster_name] = {}
        if node_name:
            c_tree[node_cluster_name][node_name] = {}
        for child_group_name, child_group in child_groups.items():
            child_cluster_name = snake_case(
                "cluster_" + node_name + "_" + child_group_name
            )
            c_tree[node_cluster_name][child_cluster_name] = cluster_shrub_1(
                child_group, False
            )
    return c_tree


def render_clusters_1(clusters):
    strs = []
    for k, v in clusters.items():
        strs.append(v.render())
    return "\n".join(strs)


def containing_cluster(path):
    if not path:
        return ''
    span = 2
    words = path if isinstance(path, list) else path.split("|") # temporary complexity while refactoring
    return ['cluster_' + "_".join(words[i:i + span]) for i in range(0, len(words), span)][-1]

def sort_labels(labels):
    return sorted([l for l in labels if re.search('[a-zA-Z]|$', l).group().islower()]) + \
           sorted([l for l in labels if not re.search('[a-zA-Z]|$', l).group().islower()])