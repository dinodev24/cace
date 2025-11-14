from flask import Flask, render_template, request, Response
from .parameter import ParameterManager
from .web.html_templates import *

import json
import logging
import mpld3
import os
import queue
import sys

parameter_manager = ParameterManager(
    max_runs=None, run_path=None, max_jobs=os.cpu_count()
)
parameter_manager.find_datasheet(os.getcwd(), False)
paramkey_paramdisplay = {
    i: j.get('display', i)
    for i, j in parameter_manager.datasheet['parameters'].items()
}
paramdisplay_paramkey = {
    j.get('display', i): i
    for i, j in parameter_manager.datasheet['parameters'].items()
}

task_queue = queue.Queue()
figures = {}
debug = False
app = Flask(__name__, template_folder='web', static_folder='web/static')


@app.route('/')
def homepage():
    sys.stdout = sys.__stdout__
    pnames = parameter_manager.get_all_pnames()
    parameter_manager.results = {}
    parameter_manager.result_types = {}
    data = [{'name': pname} for pname in pnames]

    config = None

    if os.path.exists('.cace_config.json'):
        with open('.cace_config.json') as f:
            config = json.load(f)
    else:
        with open('.cace_config.json', 'a') as f:
            f.write('{')
            f.write('    "max_runs" : null,')
            f.write('    "run_path" : null,')
            f.write(f'    "jobs" : {os.cpu_count()},')
            f.write('    "force" : false,')
            f.write('    "noplot" : false,')
            f.write('    "nosim" : false,')
            f.write('    "sequential" : false,')
            f.write('    "netlist_source" : "best",')
            f.write('    "parallel_parameters" : 4,')
            f.write('    "typ_thresh" : 10')
            f.write('}')

        with open('.cace_config.json') as f:
            config = json.load(f)

    load_config(config)

    runs = next(os.walk(parameter_manager.datasheet['paths']['runs']))[1]

    results = []
    for run in runs:
        result = []

        summary_lines = read_summary_lines(run)

        if summary_lines == None:
            results.append(
                DANGER_ALERT_TEMPLATE.render(
                    text='ERROR: summary.md not found for this run!'
                )
            )
            continue

        for row in summary_lines:
            row = row.split('|')

            if len(row) == 1:
                continue

            result.append(
                {
                    'parameter_str': row[1],
                    'tool_str': row[2],
                    'result_str': row[3],
                    'min_limit_str': row[4],
                    'min_value_str': row[5],
                    'max_limit_str': row[6],
                    'max_value_str': row[7],
                    'typ_limit_str': row[8],
                    'typ_value_str': row[9],
                    'status_str': row[10],
                }
            )

        results.append(RESULTS_SUMMARY_TEMPLATE.render(data=result))

    return render_template(
        template_name_or_list='index.html',
        data=data,
        runs=runs,
        results=results,
        config=json.dumps(config),
    )


def load_config(rd):
    parameter_manager.max_runs = rd['max_runs']
    parameter_manager.run_path = rd['run_path']
    parameter_manager.max_jobs = int(rd['jobs'])
    parameter_manager.set_runtime_options('force', rd['force'])
    parameter_manager.set_runtime_options('noplot', rd['noplot'])
    parameter_manager.set_runtime_options('nosim', rd['nosim'])
    parameter_manager.set_runtime_options('sequential', rd['sequential'])
    parameter_manager.set_runtime_options(
        'netlist_source', rd['netlist_source']
    )
    parameter_manager.set_runtime_options(
        'parallel_parameters', int(rd['parallel_parameters'])
    )


def generate_sse():
    datasheet = parameter_manager.datasheet['parameters']

    while True:
        tq_item = task_queue.get()

        if tq_item['task'] == 'end':
            for i in parameter_manager.running_threads:
                if i.param == tq_item['param']:
                    tq_item['status'] = i.result_type.name
                    if len(i.plots_dict) > 0:
                        figures[i.pname] = i.plots_dict
        elif tq_item['task'] == 'end_stream':
            if debug:
                print('ending sse stream')
            return
        if 'param' in tq_item:
            tq_item['param'] = list(datasheet.keys())[
                list(datasheet.values()).index(tq_item['param'])
            ]
        if debug:
            print(tq_item)
        yield f'data: {json.dumps(tq_item)}\n\n'


@app.route('/stream')
def stream():
    if debug:
        print('starting sse stream')
    return Response(generate_sse(), content_type='text/event-stream')


@app.route('/runsim', methods=['POST'])
def runsim():
    rd = json.loads(request.get_data())

    params = rd['selected_params']

    parameter_manager.prepare_run_dir()
    for pname in params:
        parameter_manager.queue_parameter(
            pname=pname,
            start_cb=lambda param, steps: (
                task_queue.put(
                    {
                        'task': 'start',
                        'param': param,
                        'steps': steps,
                    }
                )
            ),
            step_cb=lambda param: (
                task_queue.put({'task': 'step', 'param': param})
            ),
            cancel_cb=lambda param: (
                task_queue.put({'task': 'cancel', 'param': param})
            ),
            end_cb=lambda param: (
                task_queue.put({'task': 'end', 'param': param}),
            ),
        )

    parameter_manager.run_parameters_async()
    task_queue.put(
        {'task': 'progress', 'html': PROGRESS_TEMPLATE.render(params=params)}
    )
    return json.dumps({'success': True})


@app.route('/cancel_sim', methods=['POST'])
def cancel_sim():
    data = request.get_json()
    if debug:
        print(data)

    parameter_manager.cancel_parameter(pname=data['param'])
    return json.dumps({'success': True})


@app.route('/cancel_sims')
def cancel_sims():
    parameter_manager.cancel_parameters()
    return json.dumps({'success': True})


@app.route('/end_stream')
def end_stream():
    task_queue.put({'task': 'end_stream'})
    return json.dumps({'success': True})


@app.route('/fetch_results')
def fetch_results():
    parameter_manager.join_parameters()
    result = []
    divs = []

    summary_lines = parameter_manager.summarize_datasheet().split('\n')[7:-2]
    lengths = {
        param: len(
            list(
                parameter_manager.datasheet['parameters'][param]['spec'].keys()
            )
        )
        for param in parameter_manager.get_all_pnames()
    }
    for param in parameter_manager.get_result_types().keys():
        total = 0
        for i in parameter_manager.get_all_pnames():
            if i == param:
                for j in range(lengths[param]):
                    row = summary_lines[total + j].split('|')
                    result.append(
                        {
                            'parameter_str': row[1],
                            'tool_str': row[2],
                            'result_str': row[3],
                            'min_limit_str': row[4],
                            'min_value_str': row[5],
                            'max_limit_str': row[6],
                            'max_value_str': row[7],
                            'typ_limit_str': row[8],
                            'typ_value_str': row[9],
                            'status_str': row[10],
                        }
                    )

            total += lengths[i]

    divs.append('<br>')
    for pname in figures.keys():
        divs.append(
            f'<details>\n<summary>Figures for {paramkey_paramdisplay[pname]}</summary>'
        )
        for figure in figures[pname]:
            fig = figures[pname][figure].figure
            fig.set_tight_layout(True)
            fig.set_size_inches(fig.get_size_inches() * 1.25)
            divs.append(
                mpld3.fig_to_html(
                    fig, include_libraries=False, template_type='simple'
                )
            )

        divs.append('</details>\n<br>')
    if debug:
        print(divs)
    task_queue.put(
        {
            'task': 'results',
            'summary': RESULTS_SUMMARY_TEMPLATE.render(data=result),
            'plots': RESULTS_PLOTS_TEMPLATE.render(divs=divs),
        }
    )
    return json.dumps({'success': True})


@app.route('/refresh_history')
def refresh_history():
    runs = next(os.walk(parameter_manager.datasheet['paths']['runs']))[1]

    results = []
    for run in runs:
        result = []

        summary_lines = read_summary_lines(run)

        if summary_lines == None:
            results.append(
                DANGER_ALERT_TEMPLATE.render(
                    text='ERROR: summary.md not found for this run!'
                )
            )
            continue

        for row in summary_lines:
            row = row.split('|')

            if len(row) == 1:
                continue

            result.append(
                {
                    'parameter_str': row[1],
                    'tool_str': row[2],
                    'result_str': row[3],
                    'min_limit_str': row[4],
                    'min_value_str': row[5],
                    'max_limit_str': row[6],
                    'max_value_str': row[7],
                    'typ_limit_str': row[8],
                    'typ_value_str': row[9],
                    'status_str': row[10],
                }
            )

        results.append(RESULTS_SUMMARY_TEMPLATE.render(data=result))

    task_queue.put(
        {
            'task': 'history',
            'html': HISTORY_TEMPLATE.render(runs=runs, results=results),
        }
    )
    return json.dumps({'success': True})


def read_summary_lines(run):
    try:
        with open('runs/' + run + '/summary.md', 'r') as f:
            content = f.read()

        return content.split('\n')[7:-2]
    except FileNotFoundError:
        return None


@app.route('/save_config', methods=['POST'])
def save_config():
    data = request.get_json()
    with open('.cace_config.json', 'w') as f:
        f.write(json.dumps(data))

    load_config(data)
    return json.dumps({'success': True})


@app.route('/fetch_config')
def fetch_config():
    with open('.cace_config.json') as f:
        config = json.load(f)

    return json.dumps(config)


def web():
    try:
        host = 'localhost'
        port = 5000
        print(
            'Open the CACE web interface at: http://' + host + ':' + str(port)
        )

        sys.stdout = open(os.devnull, 'w')
        debug = '--debug' in sys.argv
        for prog in ['werkzeug', '__cace__']:
            logger = logging.getLogger(prog)
            logger.setLevel(logging.DEBUG if debug else logging.WARNING)

        app.run(debug=debug, host=host, port=port, use_reloader=False)
    finally:
        task_queue.put({'task': 'close'})
