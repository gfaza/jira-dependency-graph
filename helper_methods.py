import re
from itertools import takewhile


class Subgraph:
    key = None
    point = None
    node_sets: []
    children: {}

    def __init__(self, key, node_sets=[], children={}):
        self.key = key
        self.node_sets = node_sets
        self.children = children
        self.issue_state_edge = None

    def set_issue_state_edge(self, edge):
        self.issue_state_edge = edge

    def render_attrs(self, debug=False):
        if debug:
            attrs = {"style": ""}
        else:
            attrs = {"style": "invis"}
        attrs["label"] = 'cluster_' + self.key
        return dict_to_attrs(attrs, ';')

    def render_point(self, debug=False):
        if debug:
            attrs = {"style": "", "shape": "rarrow"}
        else:
            attrs = {"style": "invis", "shape": "point"}
        return "{key} [{attrs}]".format(
            key=self.key, attrs=dict_to_attrs(attrs)
        )

    def render_nodes(self, debug=False):
        return '\n'.join(
            ';'.join([f'"{node_key}"' for node_key in node_set if node_key])
            for node_set in self.node_sets if node_set
        )

    def render_children(self, debug=False):
        return '\n'.join([child.render(debug) for child in self.children.values()])

    def render_issue_state_edge(self, debug=False):
        return self.issue_state_edge or ''

    def render(self, debug=False):
        return """
            subgraph cluster_{key} {{
            {attrs}
            {point}
            {nodes}
            {children}
            {issue_state_edge}
            }};
            """.format(
            key=self.key,
            attrs=self.render_attrs(debug),
            point=self.render_point(debug),
            nodes=self.render_nodes(debug),
            children=self.render_children(debug),
            issue_state_edge=self.render_issue_state_edge(debug),
        )


class CardSubgraph(Subgraph):
    def render(self, debug=False):
        return """
            subgraph cluster_{key} {{
            {attrs}
            {nodes}
            {children}
            {issue_state_edge}
            }};
            """.format(
            key=self.key,
            attrs=self.render_attrs(debug),
            nodes=self.render_nodes(debug),
            children=self.render_children(debug),
            issue_state_edge=self.render_issue_state_edge(debug),
        )


class StateSubgraph(Subgraph):
    def render(self, debug=False):
        return """
            subgraph cluster_{key} {{
            {attrs}
            {point}
            {children}
            }}""".format(
            key=self.key,
            attrs=self.render_attrs(debug),
            point=self.render_point(debug),
            children=self.render_nodes(debug) + self.render_children(debug),
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
    # print(f'paths: {paths}')
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


def render_clusters_1(clusters, debug=False):
    strs = []
    for k, v in clusters.items():
        strs.append(v.render(debug))
    return "\n".join(strs)


def containing_cluster(path):
    if not path:
        return ''
    span = 2
    words = path if isinstance(path, list) else path.split("|")  # temporary complexity while refactoring
    return ['cluster_' + "_".join(words[i:i + span]) for i in range(0, len(words), span)][-1]


def sort_labels(labels):
    return sorted([l for l in labels if re.search('[a-zA-Z]|$', l).group().islower()]) + \
           sorted([l for l in labels if not re.search('[a-zA-Z]|$', l).group().islower()])


##############


def render_issue_subgraph(subgraph_tree, clusters_to_labels, workflow_states):
    debug = False

    issue_subgraphs = {}

    for issue_name, child_states in subgraph_tree.items():
        cluster_name = snake_case('cluster_{}'.format(issue_name))
        cluster_labels = clusters_to_labels.get(cluster_name, [])
        issue_state_subgraphs = {}
        for state, children in child_states.items():
            issue_state = snake_case("{} {}".format(issue_name, state))
            node_sets = gen_issue_state_subgraph_nodeset(issue_state, clusters_to_labels, children)
            child_graphs = {k: contents for k, contents in children.items() if contents}

            child_clusters = render_issue_subgraph(child_graphs, clusters_to_labels, workflow_states)
            issue_state_subgraph = Subgraph(issue_state,
                                            node_sets=node_sets,
                                            children=child_clusters)
            issue_state_subgraphs[issue_state] = issue_state_subgraph
            # test fuel
            # print(f'\nclusters_to_labels: {clusters_to_labels}\n')
            # print(f'\nworkflow_states: {workflow_states}\n')
            # print(f'\nchild_graphs: {child_graphs}\n')
            # print(f'\nchild_clusters: {child_clusters}\n')

        issue_subgraph = CardSubgraph(snake_case(issue_name),
                                      node_sets=[[issue_name], cluster_labels],
                                      children=issue_state_subgraphs)
        present_epic_state_edges_str = issue_state_edges(issue_name, child_states, workflow_states, debug)
        issue_subgraph.set_issue_state_edge(present_epic_state_edges_str)
        issue_subgraphs[snake_case(issue_name)] = issue_subgraph
    return issue_subgraphs


def gen_issue_state_subgraph_nodeset(issue_state, clusters_to_labels, children):
    state_cluster_name = snake_case('cluster_{}'.format(issue_state))
    state_cluster_labels = clusters_to_labels.get(state_cluster_name, [])
    child_node_keys = [k for k, contents in children.items() if not contents]
    node_sets = [
        [k for k in child_node_keys if k],
        [k for k in state_cluster_labels if k]
    ]
    return node_sets


def issue_state_edges(issue_name, child_states, workflow_states, debug_subgraphs):
    present_states = [snake_case(state) for state in child_states.keys()]
    present_states = list(set(workflow_states) & set(present_states))
    enumerated_workflow_states = {k: v for v, k in enumerate(workflow_states)}
    present_states.sort(key=enumerated_workflow_states.get)
    present_epic_states = [snake_case('{epic} {state}'.format(epic=issue_name, state=present_state))
                           for present_state in present_states]
    present_epic_state_edges_str = ''
    if present_epic_states:
        epic_state_edge_attrs = {'weight': '4'}
        if debug_subgraphs:
            epic_state_edge_attrs['style'] = ''
        else:
            epic_state_edge_attrs['style'] = 'invis'

        present_epic_state_edges_str = '{present_epic_state_edges} [{edge_attrs}]'.format(
            present_epic_state_edges=' -> '.join(present_epic_states),
            edge_attrs=dict_to_attrs(epic_state_edge_attrs))
    return present_epic_state_edges_str
