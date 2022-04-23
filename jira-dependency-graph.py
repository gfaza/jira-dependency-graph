#!/usr/bin/env python

from __future__ import print_function

import os

try:
    import configparser
except:
    from six.moves import configparser
import argparse
import getpass
import sys
import textwrap

import requests
from functools import reduce

from datetime import datetime, timezone

import graphviz

import re
import json
from PIL import Image

import yaml

from functools import lru_cache

import inspect

import html
from helper_methods import invert_dict, snake_case, graft_subgraph_tree_branches, \
    dict_to_attrs, containing_cluster, graphviz_node_string, create_node_key, create_edge_text, common_path, \
    sort_labels

MAX_SUMMARY_LENGTH = 30
MAX_QUERY_RESULTS = 300


def log(*args):
    print(*args, file=sys.stderr)


class JiraSearch(object):
    """ This factory will create the actual method used to fetch issues from JIRA. This is really just a closure that
        saves us having to pass a bunch of parameters all over the place all the time. """

    __base_url = None

    def __init__(self, url, auth, no_verify_ssl):
        self.__base_url = url
        self.url = url + '/rest/api/latest'
        self.auth = auth
        self.no_verify_ssl = no_verify_ssl
        self.fields = ','.join(
            ['key', 'summary', 'status', 'description', 'issuetype', 'issuelinks', 'subtasks', 'labels', 'assignee'])
        self.issue_cache = {}

    def get(self, uri, params={}):
        headers = {'Content-Type': 'application/json'}
        url = self.url + uri

        if isinstance(self.auth, str):
            return requests.get(url, params=params, cookies={'JSESSIONID': self.auth}, headers=headers,
                                verify=self.no_verify_ssl)
        else:
            return requests.get(url, params=params, auth=self.auth, headers=headers, verify=(not self.no_verify_ssl))

    def post(self, uri, file_attachment):
        headers = {
            "Accept": "application/json",
            "X-Atlassian-Token": "no-check"
        }
        url = self.url + uri
        head, tail = os.path.split(file_attachment)
        files = [
            ('file', (tail, open(file_attachment, 'rb'), 'image/png'))
        ]
        if isinstance(self.auth, str):
            return requests.post(url, cookies={'JSESSIONID': self.auth}, files=files, headers=headers,
                                 verify=self.no_verify_ssl)
        else:
            return requests.post(url, auth=self.auth, files=files, headers=headers, verify=(not self.no_verify_ssl))

    def put(self, uri, payload):
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        url = self.url + uri

        if isinstance(self.auth, str):
            return requests.put(url, cookies={'JSESSIONID': self.auth}, data=payload, headers=headers,
                                verify=self.no_verify_ssl)
        else:
            return requests.put(url, auth=self.auth, data=payload, headers=headers, verify=(not self.no_verify_ssl))

    def get_issue(self, key):
        """ Given an issue key (i.e. JRA-9) return the JSON representation of it. """
        log('Fetching ' + key)
        # we need to expand subtasks and links since that's what we care about here.
        response = self.get('/issue/%s' % key, params={'fields': self.fields})
        response.raise_for_status()
        return response.json()

    def add_attachment(self, key, file_attachment):
        """ Given an issue key (i.e. JRA-9) and file, add a file attachment to it on Jira. """
        log('Attaching %s to %s' % (file_attachment, key))
        response = self.post('/issue/%s/attachments' % key, file_attachment)
        response.raise_for_status()
        return response.json()

    def update_issue(self, key, payload):
        """ Given an issue key (i.e. JRA-9) and data payload, update the issue on Jira. """
        log('Updating ' + key)
        response = self.put('/issue/%s' % key, payload)
        response.raise_for_status()
        return response

    def query(self, query):
        log('Querying ' + query)
        response = self.get('/search', params={'jql': query, 'fields': self.fields})
        content = response.json()
        return content['issues']

    def list_ids(self, query):
        log('Querying ' + query)
        response = self.get('/search', params={'jql': query, 'fields': 'key', 'maxResults': MAX_QUERY_RESULTS})
        return [issue["key"] for issue in response.json()["issues"]]

    def get_issue_uri(self, issue_key):
        return self.__base_url + '/browse/' + issue_key

    def get_query_uri(self, jql):
        return self.__base_url + '/issues/?jql=' + requests.utils.quote(jql)

    def issue_cache_get(self, issue_key, or_set=False):
        issue = self.issue_cache.get(issue_key)
        if issue is None and or_set:
            self.issue_cache_set(self.get_issue(issue_key))
        return self.issue_cache.get(issue_key)

    def issue_cache_set(self, issue_data):
        self.issue_cache_prep(issue_data)
        issue = JiraIssue(issue_data)
        self.issue_cache[issue.get_key()] = issue

    @staticmethod
    def issue_cache_prep(issue):
        # avoiding some differences for sanity check comparison
        if 'expand' in issue.keys():
            issue.pop('expand')

    def get_issue_cache(self):
        return self.issue_cache


class JiraIssue:
    __data = None
    __level = None

    def __init__(self, data):
        self.__data = data

    def get_key(self):
        return self.__data['key']

    @staticmethod
    def get_key_from(data):
        return data['key']

    def get_issuetype_name(self):
        return self.__data['fields']['issuetype']['name']

    def get_status_name(self):
        return self.__data['fields']['status']['name']

    @staticmethod
    def get_status_name_from(data):
        return data['fields']['status']['name']

    def get_statuscategory_name(self):
        return self.__data['fields']['status']['statusCategory']['name']

    def get_labels(self):
        return self.__data['fields']['labels'] if 'labels' in self.__data['fields'] else []

    def get_subtasks(self):
        return self.__data['fields']['subtasks'] if 'subtasks' in self.__data['fields'] else []

    def get_issuelinks(self):
        return self.__data['fields']['issuelinks'] if 'issuelinks' in self.__data['fields'] else []

    def get_assignee(self):
        return self.__data['fields']['assignee']

    def get_assignee_initials(self):
        return self.get_assignee()['emailAddress'][:2].upper()

    def get_assignee_name(self):
        return self.get_assignee()['displayName']

    def get_summary(self):
        return self.__data['fields']['summary']

    @staticmethod
    def get_outward_issue_status_name(link):
        return link['outwardIssue']['fields']['status']['name']

    @staticmethod
    def get_inward_issue_status_name(link):
        return link['inwardIssue']['fields']['status']['name']

    def get_description(self):
        return self.__data['fields']['description']

    def get_level(self):
        return self.__level

    def set_level(self, level):
        self.__level = level


class GraphConfig:
    __config_dict = None

    def __init__(self, config_dict):
        self.__config_dict = config_dict

    def color_setting(self):
        return self.__config_dict.get('color-setting', {})

    def workflows(self):
        return self.__config_dict.get('workflows', [])

    def nodes(self):
        return self.__config_dict.get('nodes', [])

    def edges(self):
        return self.__config_dict.get('edges', [])

    def labels(self):
        return self.__config_dict.get('labels', [])

    def get_default_node_options(self):
        node_options = {}

        color_scheme = self.color_setting().get('color-scheme', None)
        if color_scheme is not None:
            node_options['colorscheme'] = color_scheme

        default_node_options, default_edge_options = self.get_node_options('default')
        node_options.update(default_node_options)

        return node_options

    @lru_cache(maxsize=None)
    def get_node_options(self, node_type):
        shape_options = next((item for item in self.__config_dict.get('nodes', {}) if node_type in item['name']), {})
        return shape_options.get('node-options', {}), shape_options.get('edge-options', {})

    @lru_cache(maxsize=None)
    def get_edge_options(self, parent_node_type):
        return next((item for item in self.__config_dict.get('edges', {}) if parent_node_type in item['name']), {}).get(
            'edge-options', {})

    def get_issue_color(self, issue_type_name, status_name, status_category_name):
        try:
            (fill_color, font_color) = self.get_issue_status_color(issue_type_name, status_name)
        except StopIteration:
            log("issue type '{}/{}' not found, defaulting color scheme".format(issue_type_name, status_name))
            fill_color = "/{}/{}".format('x11', self.get_status_category_color(status_category_name))
            font_color = None
        return fill_color, font_color

    def get_issue_status_color(self, issue_type_name, state_name):
        workflow_states = self.get_card_states(issue_type_name)
        if workflow_states is None:
            raise StopIteration

        fill_color = "white"
        font_color = None

        try:
            state_index = workflow_states.index(state_name.lower())
            progress_percentage = (state_index + 0.5) / float(len(workflow_states))
            fill_color_list = self.color_setting().get('fill-colors', None)
            if fill_color_list is not None:
                fill_color = self.select_from_progression(fill_color_list, progress_percentage, fill_color)
            font_color_list = self.color_setting().get('font-colors', None)
            if font_color_list is not None:
                font_color = self.select_from_progression(font_color_list, progress_percentage, font_color)
        except ValueError:
            pass

        if fill_color is not None:
            fill_color = str(fill_color)

        if font_color is not None:
            font_color = str(font_color)

        return fill_color, font_color

    @staticmethod
    def select_from_progression(ordered_list, progress_percentage, default):
        index = int(len(ordered_list) * progress_percentage)
        if ordered_list[index] != 'None':
            return ordered_list[index]
        else:
            return default

    def get_card_states(self, card_type):
        workflow_index = self.get_workflow_index(card_type)
        if workflow_index is None:
            return None
        return self.get_workflow_states(workflow_index)

    @lru_cache(maxsize=None)
    def get_workflow_states(self, workflow_index):
        return self.workflows()[workflow_index]['states']

    @lru_cache(maxsize=None)
    def get_workflow_index(self, card_type):
        return next(
            (i for i, item in enumerate(self.workflows()) if card_type.lower() in item['issue-types']),
            None)

    @staticmethod
    def get_status_category_color(status_category_name):
        status = status_category_name.upper()
        if status == 'IN PROGRESS':
            return 'yellow'
        elif status == 'DONE':
            return 'green'
        return 'white'


def build_graph_data(start_issue_key, jira, excludes, show_directions, directions, includes, issue_excludes,
                     ignore_closed, ignore_epic, ignore_subtasks, traverse, word_wrap, search_depth_limit,
                     elements_to_include, style_options, graph_config, card_meta):
    """ Given a starting image key and the issue-fetching function build up the GraphViz data representing relationships
        between issues. This will consider both subtasks and issue links.
    """

    card_states = card_meta['card_states']
    card_epics = card_meta['card_epics']
    card_supertasks = card_meta['card_supertasks']
    card_labels = card_meta['card_labels']

    def create_node_text(issue, islink=True):
        if islink:
            return create_node_key(issue.get_key())
        node_attributes = build_issue_node_attributes(issue)
        return graphviz_node_string(issue.get_key(), node_attributes)

    def build_issue_node_attributes(issue):
        node_attributes = {'href': jira.get_issue_uri(issue.get_key()),
                           'label': get_node_label(issue),
                           'style': 'filled'}

        # issue-type-specific, node attributes
        node_options, edge_options = graph_config.get_node_options(issue.get_issuetype_name().lower())
        node_attributes.update(node_options)

        # issue-state specific, node coloring
        fill_color, font_color = graph_config.get_issue_color(issue.get_issuetype_name(),
                                                              issue.get_status_name(),
                                                              issue.get_statuscategory_name())
        node_attributes['fillcolor'] = fill_color
        if font_color is not None:
            node_attributes['fontcolor'] = font_color
        return node_attributes

    def get_node_label(issue):
        summary = issue.get_summary()
        if word_wrap:
            if len(summary) > MAX_SUMMARY_LENGTH:
                # split the summary into multiple lines adding a \n to each line
                summary = textwrap.fill(summary, MAX_SUMMARY_LENGTH)
        else:
            # truncate long labels with "...", but only if the three dots are replacing more than two characters
            # -- otherwise the truncated label would be taking more space than the original.
            if len(summary) > MAX_SUMMARY_LENGTH + 2:
                summary = summary[:MAX_SUMMARY_LENGTH] + '...'
        if style_options.get('html_stylize', False):
            summary = html.escape(summary)
            summary = summary.replace('\n', '<br/>')
            table_attributes = 'border="0" cellspacing="2" cellpadding="3"'
            th_font_attributes = 'face="Impact"'
            td_font_attributes = ""
            if 'state' in elements_to_include:
                if 'assignee' in elements_to_include and issue.get_assignee() is not None:
                    node_label = '<<table {table_attributes}>' \
                                 '<tr>' \
                                 '<td align="center"><font {th_font_attributes}>{issue_key}</font></td>' \
                                 '<td align="center"><font {th_font_attributes}>{issue_state}</font></td>' \
                                 '<td align="center"><font {th_font_attributes}>{issue_assignee}</font></td>' \
                                 '</tr>' \
                                 '<tr><td align="center" colspan="3"><font {td_font_attributes}>{issue_summary}</font></td></tr>' \
                                 '</table>>' \
                        .format(table_attributes=table_attributes, th_font_attributes=th_font_attributes,
                                issue_key=issue.get_key(), issue_state=issue.get_status_name().upper(),
                                issue_assignee=issue.get_assignee_initials(),
                                td_font_attributes=td_font_attributes,
                                issue_summary=summary)
                else:
                    node_label = '<<table {table_attributes}>' \
                                 '<tr>' \
                                 '<td align="center"><font {th_font_attributes}>{issue_key}</font></td>' \
                                 '<td align="center"><font {th_font_attributes}>{issue_state}</font></td>' \
                                 '</tr>' \
                                 '<tr><td align="center" colspan="2"><font {td_font_attributes}>{issue_summary}</font></td></tr>' \
                                 '</table>>' \
                        .format(table_attributes=table_attributes, th_font_attributes=th_font_attributes,
                                issue_key=issue.get_key(), issue_state=issue.get_status_name().upper(),
                                td_font_attributes=td_font_attributes,
                                issue_summary=summary)
            else:
                node_label = '<<table {table_attributes}>' \
                             '<tr>' \
                             '<td align="center"><font {th_font_attributes}>{issue_key}</font></td>' \
                             '</tr>' \
                             '<tr><td align="center" colspan="1"><font {td_font_attributes}>{issue_summary}</font></td></tr>' \
                             '</table>>' \
                    .format(table_attributes=table_attributes, th_font_attributes=th_font_attributes,
                            issue_key=issue.get_key(), td_font_attributes=td_font_attributes,
                            issue_summary=summary)
        else:
            summary = summary.replace('"', '\\"')
            summary = summary.replace('\n', '\\n')
            if 'state' in elements_to_include:
                if 'assignee' in elements_to_include and issue.get_assignee() is not None:
                    node_label = '{} {} {}\\n{}'.format(issue.get_key(), issue.get_status_name(),
                                                        issue.get_assignee_initials(), summary)
                else:
                    node_label = '{} {}\\n{}'.format(issue.get_key(), issue.get_status_name(), summary)
            else:
                node_label = '{}\\n{}'.format(issue.get_key(), summary)
        return node_label

    def process_link(issue, link):
        issue_key = issue.get_key()

        if 'outwardIssue' in link:
            direction = 'outward'
        elif 'inwardIssue' in link:
            direction = 'inward'
        else:
            return

        if direction not in directions:
            return

        linked_issue = link[direction + 'Issue']
        linked_issue_key = JiraIssue.get_key_from(linked_issue)
        if linked_issue_key in issue_excludes:
            log('Skipping ' + linked_issue_key + ' - explicitly excluded')
            return

        link_type = link['type'][direction]

        if ignore_closed:
            if ('inwardIssue' in link) and (JiraIssue.get_inward_issue_status_name(link) in 'Closed'):
                log('Skipping ' + linked_issue_key + ' - linked key is Closed')
                return
            if ('outwardIssue' in link) and (JiraIssue.get_outward_issue_status_name(link) in 'Closed'):
                log('Skipping ' + linked_issue_key + ' - linked key is Closed')
                return

        if includes not in linked_issue_key:
            return

        if link_type.strip() in excludes:
            return linked_issue_key, None

        arrow = ' => ' if direction == 'outward' else ' <= '
        log(issue_key + arrow + link_type + arrow + linked_issue_key)

        edge_options = {'label': link_type}
        if link_type in ["blocks", "is blocking", "is blocked by"]:
            edge_options.update(graph_config.get_edge_options('block'))
            if issue.get_statuscategory_name().upper() == 'DONE':
                edge_options.update({'color': 'black'})

        if direction not in show_directions:
            edge = None
        else:
            edge_nodes = [create_node_key(issue_key),
                          create_node_key(linked_issue_key)]

            # orient blockers as dependencies (away from graph root)
            if link_type in ["blocks", "is blocking", "is blocked by"]:
                edge_options['dir'] = 'back'
                edge_nodes.reverse()

            # orient related as same rank
            if link_type in ["relates to"]:
                edge_options['constraint'] = 'false'
                edge_options['dir'] = 'none'

            edge = create_edge_text(edge_nodes[0], edge_nodes[1], edge_options)

        return linked_issue_key, edge

    # since the graph can be cyclic we need to prevent infinite recursion
    seen = []

    sanity_check_issue_cache = False

    def walk(issue_key, graph, remaining_depth_limit=None):
        """ issue is the JSON representation of the issue """
        log("Walking: {}, remaining_depth_limit={}".format(issue_key, remaining_depth_limit))

        issue_cache_sanity_check(issue_key)
        issue = jira.issue_cache_get(issue_key, or_set=True)
        if issue_key not in seen:
            seen.append(issue_key)

        issue_status_name = issue.get_status_name()

        if ignore_closed and (issue_status_name in 'Closed'):
            log('Skipping ' + issue_key + ' - it is Closed')
            return graph

        if not traverse and ((project_prefix + '-') not in issue_key):
            log('Skipping ' + issue_key + ' - not traversing to a different project')
            return graph
        graph.append(create_node_text(issue, islink=False))
        if 'labels' in elements_to_include:
            card_labels[issue_key] = issue.get_labels()

        current_depth = -1
        if remaining_depth_limit is not None:
            # update issue depth to the minimum depth observed
            current_depth = search_depth_limit - remaining_depth_limit
            if issue.get_level() is not None:
                current_depth = min(current_depth, issue.get_level())

            # decrease the remaining depth limit, and stop recursion if we've reached that limit
            remaining_depth_limit = search_depth_limit - current_depth
            remaining_depth_limit -= 1
            if remaining_depth_limit < 0:
                return graph

        issue.set_level(current_depth)

        issuetype_name = issue.get_issuetype_name()
        if issuetype_name != 'Epic':
            card_states[issue_key] = issue_status_name.upper()

        children = []

        if not ignore_subtasks:
            if issuetype_name == 'Epic' and not ignore_epic:
                if ignore_closed:
                    issues = jira.query('"Epic Link" = "%s" AND status != Closed' % issue_key)
                else:
                    issues = jira.query('"Epic Link" = "%s"' % issue_key)
                for subtask in issues:
                    subtask_key = JiraIssue.get_key_from(subtask)

                    log(issue_key + ' => has issue => ' + subtask_key)
                    edge = create_edge_text(create_node_key(issue_key),
                                            create_node_key(subtask_key),
                                            graph_config.get_edge_options('epic'))

                    graph.append(edge)
                    children.append(subtask_key)
                    card_epics[subtask_key] = issue_key

                    # let's avoid re-querying this when we iterate over children, since we've already got it here
                    issue_cache_sanity_check(subtask)
                    if subtask_key not in jira.get_issue_cache():
                        jira.issue_cache_set(subtask)

            if not ignore_subtasks:
                for subtask in issue.get_subtasks():
                    subtask_key = JiraIssue.get_key_from(subtask)
                    if ignore_closed and (JiraIssue.get_status_name_from(subtask) in 'Closed'):
                        log('Skipping Subtask ' + subtask_key + ' - it is Closed')
                        continue
                    log(issue_key + ' => has subtask => ' + subtask_key)
                    edge = create_edge_text(create_node_key(issue_key),
                                            create_node_key(subtask_key),
                                            graph_config.get_edge_options('subtask'))
                    graph.append(edge)
                    children.append(subtask_key)
                    card_supertasks[subtask_key] = issue_key
        for other_link in issue.get_issuelinks():
            result = process_link(issue, other_link)
            if result is not None:
                (linked_issue_key, edge) = result
                log('Appending ' + linked_issue_key)
                children.append(linked_issue_key)
                if edge is not None:
                    graph.append(edge)
        # now construct graph data for all subtasks and links of this issue
        # for child_key in (x for x in children if x not in seen and x not in issue_excludes):
        for child_key in (x for x in children if x not in issue_excludes):
            seen_child = jira.issue_cache_get(child_key)
            if (not seen_child) or (seen_child.get_level() is None) or (seen_child.get_level() > current_depth + 1):
                walk(child_key, graph, remaining_depth_limit)
        return graph

    def issue_cache_sanity_check(issue_key_or_issue):
        if not sanity_check_issue_cache:
            return

        if isinstance(issue_key_or_issue, dict):
            issue = issue_key_or_issue
            issue_key = JiraIssue.get_key_from(issue_key_or_issue)
        else:
            issue = None
            issue_key = issue_key_or_issue

        if issue_key in jira.issue_cache.keys():
            if issue is None:
                issue = jira.get_issue(issue_key)
            jira.issue_cache_prep(issue)
            if jira.issue_cache[issue_key] != issue:
                log('ISSUE_CACHE != ISSUE:')
                log('issue_cache:')
                log(jira.issue_cache[issue_key])
                log('issue:')
                log(issue)

    def color_demo(graph):
        # demonstrate issue color configs
        for workflow_idx, workflow in enumerate(graph_config.workflows()):
            issue_type_name = workflow['issue-types'][0]
            issue_type_nodes = []
            issue_key_prior = None
            for state_idx, state in enumerate(workflow['states']):
                issue_key = '{}-00{}'.format(issue_type_name, state_idx)
                issue_fields = {
                    'summary': 'summary',
                    'status': {
                        'name': state,
                        'statusCategory': {
                            'name': 'name'
                        }
                    },
                    'issuetype': {
                        'name': issue_type_name
                    }
                }
                issue = {'key': issue_key, 'fields': issue_fields}
                issue_type_nodes.append(create_node_text(issue, islink=False))
                if issue_key_prior is not None:
                    graph.append(create_edge_text(create_node_key(issue_key_prior),
                                                  create_node_key(issue_key)))
                issue_key_prior = issue_key

            graph.append('subgraph {{{}}}'.format(';'.join(issue_type_nodes)))
        return graph

    if start_issue_key == 'color-demo':
        return color_demo([]), seen

    project_prefix = start_issue_key.split('-', 1)[0]
    return walk(start_issue_key, [], search_depth_limit), seen


def update_issue_graph(jira, issue_key, file_attachment_path):
    """ Given a key and the issue-fetching function, insert/update the auto-generated graph to the card's description.
    """

    def update(update_issue_key, update_file_attachment_path):
        """ issue is the JSON representation of the issue """
        # generate the inline image markup of the newly attached image
        _, attachment_name = os.path.split(update_file_attachment_path)
        width, height = Image.open(update_file_attachment_path).size
        image_tag = "%s|width=%d,height=%d" % (attachment_name, width, height)

        # append or replace the description's inline image
        issue = jira.get_issue(update_issue_key)
        description = issue.get_description()
        previous_image = re.search(r"^(h3\.\s*Jira Dependency Graph\s+\!)([^\!]+)(\!)", description, re.MULTILINE)
        if previous_image is not None:
            # old_attachment_name = previous_image.group(2) # leaving deletion to humans, just in case
            description = description.replace(previous_image.group(0),
                                              previous_image.group(1) + image_tag + previous_image.group(3))
        else:
            description = description + "\n\nh3.Jira Dependency Graph\n\n!" + image_tag + "!\n"

        # update the card's description
        updated_fields = {"fields": {"description": description}}
        payload = json.dumps(updated_fields)
        jira.update_issue(update_issue_key, payload)

    return update(issue_key, file_attachment_path)


def create_graph_string(graph_data, graph_attributes, default_node_attributes):
    # concentrate = "true";
    # compound = "true";
    return 'digraph{{{};node [{}];\n{}}}'.format(dict_to_attrs(graph_attributes, ';'),
                                                 dict_to_attrs(default_node_attributes),
                                                 ';\n'.join(graph_data))


def create_graph_images(graph_string, image_file):
    """ Given a formatted blob of graphviz chart data[1], generate and store the resulting image to disk.
    """

    src = graphviz.Source(graph_string)
    log('Writing ' + image_file + ".png")
    src.render(image_file, format="png")  # for updating the card description, mostly
    log('Writing ' + image_file + ".pdf")
    src.render(image_file, format="pdf")  # fun b/c nodes are hyperlinks to jira, allowing navigation from the graph


def print_graph(graph_string):
    print(graph_string)


def parse_args(choice_of_org=None):
    config = configparser.ConfigParser()
    config.read('./config/personal-config.ini')
    if choice_of_org is None:
        choice_of_org = config.sections()[0]

    default_host = config[choice_of_org]['JIRA_HOST']
    default_user = config[choice_of_org]['JIRA_USER']
    default_pass = config[choice_of_org]['JIRA_PASS']

    parser = argparse.ArgumentParser()

    parser.add_argument('-o', '--org', dest='org', default=choice_of_org, help='JIRA org')

    parser.add_argument('-u', '--user', dest='user', default=default_user, help='Username to access JIRA')
    parser.add_argument('-p', '--password', dest='password', default=default_pass, help='Password to access JIRA')
    parser.add_argument('-c', '--cookie', dest='cookie', default=None, help='JSESSIONID session cookie value')
    parser.add_argument('-N', '--no-auth', dest='no_auth', action='store_true', default=False,
                        help='Use no authentication')
    parser.add_argument('-j', '--jira', dest='jira_url', default=default_host, help='JIRA Base URL (with protocol)')
    parser.add_argument('-f', '--file', dest='image_file', default='issue_graph', help='Filename to write image to')
    parser.add_argument('-l', '--local', action='store_true', default=False, help='Render graphviz code to stdout')
    parser.add_argument('-e', '--ignore-epic', action='store_true', default=False,
                        help='Don''t follow an Epic into it''s children issues')
    parser.add_argument('-x', '--exclude-link', dest='excludes', default=[], action='append',
                        help='Exclude link type(s)')
    parser.add_argument('-ic', '--ignore-closed', dest='closed', action='store_true', default=False,
                        help='Ignore closed issues')
    parser.add_argument('-i', '--issue-include', dest='includes', default='', help='Include issue keys')
    parser.add_argument('-xi', '--issue-exclude', dest='issue_excludes', action='append', default=[],
                        help='Exclude issue keys; can be repeated for multiple issues')
    parser.add_argument('-s', '--show-directions', dest='show_directions', default=['inward', 'outward'],
                        help='which directions to show (inward, outward)')
    parser.add_argument('-d', '--directions', dest='directions', default=['inward', 'outward'],
                        help='which directions to walk (inward, outward)')
    parser.add_argument('--jql', dest='jql_query', default=None,
                        help='JQL search for issues (e.g. \'project = JRADEV\')')
    parser.add_argument('-ns', '--node-shape', dest='node_shape', default='box',
                        help='which shape to use for nodes (circle, box, ellipse, etc)')
    parser.add_argument('-t', '--ignore-subtasks', action='store_true', default=False,
                        help='Don''t include sub-tasks issues')
    parser.add_argument('-T', '--dont-traverse', dest='traverse', action='store_false', default=True,
                        help='Do not traverse to other projects')
    parser.add_argument('-w', '--word-wrap', dest='word_wrap', default=False, action='store_true',
                        help='Word wrap issue summaries instead of truncating them')
    parser.add_argument('-dl', '--depth-limit', dest='depth_limit', default=None, help='Link depth limit', type=int)
    parser.add_argument('--html-stylize', dest='html_stylize', action='store_true', default=False,
                        help='Stylize with HTML labels')
    parser.add_argument('--employ-subgraphs', dest='employ_subgraphs', action='store_true', default=False,
                        help='Group cards by parent and state')
    parser.add_argument('--include-state', dest='include_state', action='store_true', default=False,
                        help='Include issue state')
    parser.add_argument('--include-assignee', dest='include_assignee', action='store_true', default=False,
                        help='Include issue assignee')
    parser.add_argument('--include-labels', dest='include_labels', action='store_true', default=False,
                        help='Include issue labels')
    parser.add_argument('--hide-label', dest='label_hide', action='append', default=[],
                        help='Hide issue label; can be repeated for multiple labels')
    parser.add_argument('--include-arguments', dest='include_arguments', action='store_true', default=False,
                        help='Include graph arguments')
    parser.add_argument('--graph-rank-direction', dest='graph_rank_direction', default='TB',
                        help='Graph rank direction')
    parser.add_argument('-iu', '--issue-update', dest='issue_update', default='', help='Update issue description graph')
    parser.add_argument('--no-verify-ssl', dest='no_verify_ssl', default=False, action='store_true',
                        help='Don\'t verify SSL certs for requests')
    parser.add_argument('issues', nargs='*', help='The issue key (e.g. JRADEV-1107, JRADEV-1391)')
    return parser.parse_args()


def filter_duplicates(lst):
    # Enumerate the list to restore order lately; reduce the sorted list; restore order
    def append_unique(acc, item):
        return acc if acc[-1][1] == item[1] else acc.append(item) or acc

    srt_enum = sorted(enumerate(lst), key=lambda i_val: i_val[1])
    return [item[1] for item in sorted(reduce(append_unique, srt_enum, [srt_enum[0]]))]


def main():
    config = configparser.ConfigParser()
    config.read('./config/personal-config.ini')

    # parse args as if for default org.  if parsed org is not the default org, then re-parse
    options = parse_args()
    if options.org != config.sections()[0]:
        options = parse_args(options.org)

    if options.cookie is not None:
        # Log in with browser and use --cookie=ABCDEF012345 commandline argument
        auth = options.cookie
    elif options.no_auth is True:
        # Don't use authentication when it's not needed
        auth = None
    else:
        # Basic Auth is usually easier for scripts like this to deal with than Cookies.
        user = options.user if options.user is not None \
            else input('Username: ')
        password = options.password if options.password is not None \
            else getpass.getpass('Password: ')
        auth = (user, password)
    # redact sensitive keys asap
    redact_namespace(options)

    jira = JiraSearch(options.jira_url, auth, options.no_verify_ssl)

    if options.jql_query is not None:
        options.issues.extend(jira.list_ids(options.jql_query))

    elements_to_include = []
    if options.include_labels:
        elements_to_include.append('labels')
    if options.include_state:
        elements_to_include.append('state')
    if options.include_assignee:
        elements_to_include.append('assignee')
    if options.include_arguments:
        elements_to_include.append('graph_arguments')

    style_options = {'html_stylize': options.html_stylize}

    try:
        with open('./config/{}-config.yml'.format(options.org.lower()), 'r') as file:
            color_config = yaml.safe_load(file)
    except FileNotFoundError:
        color_config = {}

    graph_config = GraphConfig(color_config)

    graph = []
    seen = []
    card_meta = {
        'card_states': {},
        'card_epics': {},
        'card_supertasks': {},
        'card_labels': {},
    }

    walk_depth_limit = None if options.depth_limit is None else options.depth_limit + 1

    # for issue in (x for x in options.issues if x not in seen and x not in options.issue_excludes):
    for issue in (x for x in options.issues if x not in options.issue_excludes):
        (g, s) = build_graph_data(issue, jira, options.excludes, options.show_directions, options.directions,
                                  options.includes, options.issue_excludes, options.closed, options.ignore_epic,
                                  options.ignore_subtasks, options.traverse, options.word_wrap, walk_depth_limit,
                                  elements_to_include, style_options, graph_config, card_meta)
        graph = graph + g
        seen = seen + s

    # select only cards that are within the (conditionally) desired depth

    log('Dumping retro-testing fuel ...')
    log(f'jira_issue_cache = {jira.get_issue_cache()}')
    log(f'graph = {graph}')

    card_states = card_meta['card_states']
    card_epics = card_meta['card_epics']
    card_supertasks = card_meta['card_supertasks']
    card_labels = card_meta['card_labels']

    log(f'card_states = {card_states}')
    log(f'card_epics = {card_epics}')
    log(f'card_supertasks = {card_supertasks}')
    log(f'card_labels = {card_labels}')

    log(f'graph_config = {graph_config}')
    log(f'elements_to_include = {elements_to_include}')
    log(f'options = {options}')

    cards_beyond_depth_limit = []
    if options.depth_limit is not None:
        card_levels = {key: issue.get_level() for key, issue in jira.get_issue_cache().items()
                       if issue.get_level() is not None}
        # log(f'card_levels: {card_levels}')
        cards_beyond_depth_limit = [k for k, depth in card_levels.items() if depth > options.depth_limit]
        graph = [line for line in graph if
                 all(create_node_key(issue_key) not in line for issue_key in cards_beyond_depth_limit)]

        # render cards outside of the initial depth, a little smaller
        depth_relative_node_graph = []
        for line in graph:
            match_result = re.match(r'^"([\w\-]+)"', line)
            if match_result:
                node_issue_key = match_result.group(1)
                if card_levels[node_issue_key] > 0:
                    penwidth = '0.5'
                    fontsize = '12'
                    line = re.sub(r'\]$', ',penwidth="{}",fontsize="{}"]'.format(penwidth, fontsize), line)
            depth_relative_node_graph.append(line)
        graph = depth_relative_node_graph

    labels_to_cards = {}
    if 'labels' in elements_to_include:
        label_tree = []

        labels_to_consolidate = {}
        issue_labels = graph_config.labels()

        # map labels to consolidated group label
        for label_to_consolidate in [{group_item: item['name'] for group_item in item['group']}
                                     for item in issue_labels if 'group' in item.keys()]:
            labels_to_consolidate.update(label_to_consolidate)

        # map labels to be ignored
        for label_to_consolidate in [{group_item: None for group_item in item['ignore']}
                                     for item in issue_labels if 'ignore' in item.keys()]:
            labels_to_consolidate.update(label_to_consolidate)

        labels_to_hide = []
        if options.label_hide:
            labels_to_hide = options.label_hide

        # build cards_to_labels, omitting cards outside of depth limit
        cards_to_labels = card_labels
        cards_to_labels = {k: v for k, v in cards_to_labels.items() if k not in cards_beyond_depth_limit}
        labels_to_cards = invert_dict(cards_to_labels)

        # re-label as necessary
        for label_found in list(labels_to_cards):
            label_clean = labels_to_consolidate.get(label_found.lower(), label_found.lower())
            if not label_clean:
                labels_to_cards.pop(label_found)
                continue
            if label_found == label_clean:
                continue
            if not label_clean in labels_to_cards.keys():
                labels_to_cards[label_clean] = []
            labels_to_cards[label_clean] = labels_to_cards[label_clean] + [k for k in labels_to_cards.pop(label_found)
                                                                           if k not in labels_to_cards[label_clean]]

        # orient 'root' labels toward the beginning of the graph, and all other labels toward the end of the graph
        for label, issue_keys in labels_to_cards.items():
            orientation = next((item for item in issue_labels if label == item.get('name')), {}).get('orientation',
                                                                                                     'leaf')
            label_node_options, label_edge_options = graph_config.get_node_options('label')

            # label node attributes
            label_node_attributes = label_node_options.copy()
            label_node_attributes['href'] = jira.get_query_uri(
                'labels in ({}) and not statusCategory = Done'.format(label.replace('/', ', ')))

            if orientation == 'leaf':
                label_node_attributes['orientation'] = '180'

            # label edge attributes
            label_edge_attributes = label_edge_options.copy()

            if label in labels_to_hide:
                label_node_attributes['style'] = label_edge_attributes['style'] = 'invis'

            label_node_text = graphviz_node_string(label, label_node_attributes)
            label_tree.append(label_node_text)

            for issue_key in issue_keys:
                edge_nodes = [create_node_key(issue_key), create_node_key(label)]
                if orientation == 'root':
                    edge_nodes.reverse()

                label_edge_text = create_edge_text(edge_nodes[0], edge_nodes[1], label_edge_attributes)
                label_tree.append(label_edge_text)

    digraph = []

    if label_tree:
        # digraph = digraph + ['\n\n// Labels'] + sorted(set(label_tree), key=lambda s: s.lower())
        # digraph = digraph + ['\n\n// Labels'] + list(set(label_tree))
        digraph = digraph + ['\n\n// Labels'] + sort_labels(set(label_tree))

    if options.employ_subgraphs:
        subgraph_tree = generate_subgraphs(card_epics, card_states, card_supertasks, labels_to_cards, graph,
                                           graph_config)
        digraph = digraph + ['\n\n// Subgraphs'] + subgraph_tree

    if graph:
        digraph = digraph + ['\n\n// Graph'] + filter_duplicates(graph)

    graph_attributes = {'rankdir': options.graph_rank_direction}
    if 'graph_arguments' in elements_to_include:
        sys_args = sys.argv[1:]
        sys_args.sort(key=lambda x: x[0:6] == '--jql=')
        sys_args_str = ' '.join(sys_args).replace('"', '\\"').replace("'", "\'")
        sys_args_str = sys_args_str.replace('--jql=', '\\n--jql=')
        graph_attributes.update({'labelloc': 't', 'labeljust': 'c', 'label': sys_args_str})

    default_node_attributes = {'shape': options.node_shape}
    default_node_attributes.update(graph_config.get_default_node_options())

    graph_string = create_graph_string(digraph, graph_attributes, default_node_attributes)

    # TODO: consecutive semi-colons cause issues - better to avoid the prior to this point
    graph_string = re.sub(r';\s+;', ';', graph_string)

    if options.local:
        print_graph(graph_string)
    else:
        # print_graph(graph_string)

        # override the default image name with one that indicates issues queried
        image_filename = options.image_file
        if options.image_file == 'issue_graph':
            if options.jql_query:
                issues_str = re.sub(r'[^\w]+', '_', options.jql_query).strip('_')
            elif options.issues:
                issues_str = '-'.join(options.issues[:10])
            else:
                issues_str = 'graph'
            timestamp_str = datetime.now().isoformat(timespec='seconds').translate({ord(c): None for c in ":-"})
            image_filename = issues_str + '.graph.' + timestamp_str
        image_filename = './out/' + image_filename

        create_graph_images(graph_string, image_filename)
        if options.issue_update:
            # attach the pdf
            file_attachment_path = image_filename + ".pdf"
            jira.add_attachment(options.issue_update, file_attachment_path)

            # attach the png
            file_attachment_path = image_filename + ".png"
            jira.add_attachment(options.issue_update, file_attachment_path)

            # update the issue description with the updated png
            update_issue_graph(jira, options.issue_update, file_attachment_path)


def redact_namespace(config, sensitive_keys=['user', 'password']):
    for key in sensitive_keys:
        delattr(config, key)


def generate_subgraphs(card_epics, card_states, card_supertasks, labels_to_cards, graph, graph_config):
    subgraph_tree = {}

    for line in graph:
        # detect and treat node entry
        match_result = re.match(r'^"([A-Z]+-[0-9]+)" *?(?!-)', line)
        if match_result:
            node_issue_key = match_result.group(1)
            node_issue_card_epic = card_epics.get(node_issue_key, '')
            node_issue_card_supertask = card_supertasks.get(node_issue_key, '')
            node_issue_card_state = card_states.get(node_issue_key, '')

            node_issue_parent = node_issue_card_supertask or node_issue_card_epic

            build_subgraph_tree(card_epics, card_supertasks, node_issue_card_state, node_issue_key, node_issue_parent,
                                subgraph_tree)

    graft_subgraph_tree_branches(subgraph_tree)

    log(
        f'subgraph_tree = {subgraph_tree}\n'
        f'labels_to_cards = {labels_to_cards}'
    )
    labels_to_paths = {label: common_path(subgraph_tree, keys) for label, keys in labels_to_cards.items()}

    labels_to_clusters = {k: containing_cluster(v) for k, v in labels_to_paths.items()}
    log(
        f'labels_to_clusters = {labels_to_clusters}'
    )
    clusters_to_labels = invert_dict(labels_to_clusters)
    log(
        f'clusters_to_labels = {clusters_to_labels}'
    )

    subgraph_tree_str = render_issue_subgraph(subgraph_tree, clusters_to_labels, graph_config)
    subgraph_tree_str = re.sub(r';\s+;', ';', subgraph_tree_str)
    return [subgraph_tree_str]


def build_subgraph_tree(card_epics, card_supertasks, node_issue_card_state, node_issue_key, node_issue_parent,
                        subgraph_tree):
    if node_issue_parent or node_issue_key not in (list(card_epics.values()) + list(card_supertasks.values())):
        if not node_issue_parent in subgraph_tree.keys():
            subgraph_tree[node_issue_parent] = {}
        if not node_issue_card_state in subgraph_tree[node_issue_parent].keys():
            subgraph_tree[node_issue_parent][node_issue_card_state] = {}
        if not node_issue_key in subgraph_tree[node_issue_parent][node_issue_card_state].keys():
            subgraph_tree[node_issue_parent][node_issue_card_state][node_issue_key] = {}


def render_issue_subgraph(subgraph_tree, clusters_to_labels, graph_config):
    debug_subgraphs = False
    subgraph_attrs = {}
    if not debug_subgraphs:
        subgraph_attrs = {'style': 'invis'}
    if debug_subgraphs:
        subgraph_node_attrs = {'shape': 'rarrow'}
    else:
        subgraph_node_attrs = {'style': 'invis', 'shape': 'point'}
    subgraph_strs = []
    for issue_name, child_states in subgraph_tree.items():
        cluster_name = snake_case('cluster_{}'.format(issue_name))
        cluster_labels = clusters_to_labels.get(cluster_name, [])
        state_subgraph_strs = ''
        state_subgraph_points = []
        for state, children in child_states.items():
            issue_state = snake_case("{} {}".format(issue_name, state))
            state_cluster_name = snake_case('cluster_{}'.format(issue_state))
            state_cluster_labels = clusters_to_labels.get(state_cluster_name, [])
            state_cluster_label_strs = "\n".join(['"{e}"'.format(e=e) for e in state_cluster_labels if e])
            state_subgraph_strs = state_subgraph_strs + "subgraph {state_cluster_name} {{\n{sg_attr_str}\n{issue_state}[{sgn_attr_str}];\n{child_clusters}\n}};\n".format(
                state_cluster_name=state_cluster_name,
                issue_state=issue_state,
                child_clusters=render_issue_subgraph(children, clusters_to_labels,
                                                     graph_config) + state_cluster_label_strs,
                sg_attr_str=dict_to_attrs({**subgraph_attrs, 'label': state_cluster_name}, ';'),
                sgn_attr_str=dict_to_attrs(subgraph_node_attrs, ';'),
            )
            state_subgraph_points.append(issue_state)

        present_epic_state_edges_str = issue_state_edges(issue_name, child_states, graph_config, debug_subgraphs)

        state_subgraph_strs = state_subgraph_strs + present_epic_state_edges_str

        if state_subgraph_strs:
            elements = [issue_name if issue_name else ''] + cluster_labels
            elements = "\n".join(['"{e}"'.format(e=e) for e in elements if e])
            subgraph_strs.append(
                "subgraph {cluster_name} {{\n{sg_attr_str}\n{issue_name}\n{child_clusters}\n}};\n".format(
                    cluster_name=cluster_name,
                    issue_name=elements,
                    child_clusters=state_subgraph_strs,
                    sg_attr_str=dict_to_attrs({**subgraph_attrs, 'label': cluster_name}, ';'),
                    sgn_attr_str=dict_to_attrs(subgraph_node_attrs, ';'),
                ))
        else:
            elements = [issue_name if issue_name else ''] + cluster_labels
            elements = "\n".join(['"{e}"'.format(e=e) for e in elements if e])
            subgraph_strs.append("{issue_name}".format(
                issue_name=elements,
            ))

    return "\n".join(subgraph_strs)


def issue_state_edges(issue_name, child_states, graph_config, debug_subgraphs):
    workflow_states = ['open', 'ready to plan'] + [snake_case(state) for state in graph_config.get_card_states('story')]
    present_states = [snake_case(state) for state in child_states.keys()]
    present_states = list(set(workflow_states) & set(present_states))
    enumerated_workflow_states = {k: v for v, k in enumerate(workflow_states)}
    present_states.sort(key=enumerated_workflow_states.get)
    present_epic_states = [snake_case('{epic} {state}'.format(epic=issue_name, state=present_state))
                           for present_state in present_states]
    present_epic_state_edges_str = ''
    if present_epic_states:
        epic_state_edge_attrs = {'weight': '4'}
        if not debug_subgraphs:
            epic_state_edge_attrs['style'] = 'invis'

        present_epic_state_edges_str = '{present_epic_state_edges} [{edge_attrs}]'.format(
            present_epic_state_edges=' -> '.join(present_epic_states),
            edge_attrs=dict_to_attrs(epic_state_edge_attrs))
    return present_epic_state_edges_str


if __name__ == '__main__':
    main()
