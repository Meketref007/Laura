"""Shell auto-completion for the Laura CLI.

Generate completion scripts for bash, zsh, and PowerShell.

Usage:
    laura completion bash  > /etc/bash_completion.d/laura
    laura completion zsh   > /usr/share/zsh/site-functions/_laura
    laura completion powershell > _laura.ps1
"""

from __future__ import annotations

import argparse
import sys


def _iter_subcommands(parser: argparse.ArgumentParser, prefix: str = "") -> list[dict]:
    commands: list[dict] = []
    if not parser._subparsers:
        return commands
    for action in parser._subparsers._group_actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for name, subparser in action.choices.items():
            full_name = f"{prefix} {name}" if prefix else name
            help_text = (subparser.description or subparser.help or "").strip()
            entry = {"name": name, "full": full_name, "help": help_text, "args": [], "subcommands": []}
            for sub_action in subparser._actions:
                if isinstance(sub_action, argparse._SubParsersAction):
                    entry["subcommands"] = _iter_subcommands(subparser, full_name)
                elif isinstance(sub_action, argparse._StoreAction) or isinstance(sub_action, argparse._StoreTrueAction) or isinstance(sub_action, argparse._StoreFalseAction):
                    opts = {
                        "flags": sub_action.option_strings[:],
                        "dest": sub_action.dest,
                        "metavar": sub_action.metavar or sub_action.type.__name__.upper() if sub_action.type else "VALUE",
                        "help": (sub_action.help or "").strip(),
                        "choices": sub_action.choices,
                        "required": sub_action.required,
                        "nargs": sub_action.nargs,
                        "const": sub_action.const if isinstance(sub_action, (argparse._StoreTrueAction, argparse._StoreFalseAction)) else None,
                    }
                    if isinstance(sub_action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
                        opts["type"] = "flag"
                    else:
                        opts["type"] = "arg"
                    entry["args"].append(opts)
            commands.append(entry)
    return commands


def _escape(s: str) -> str:
    return s.replace("'", "'\\''")


def generate_bash_script(commands: list[dict]) -> str:
    lines = [
        "# bash completion for laura",
        "_laura_completions() {",
        "  local cur prev words cword",
        '  _init_completion || return',
        "",
        '  if [[ $cword -eq 1 ]]; then',
        "    COMPREPLY=($(compgen -W \"",
    ]
    top_cmds = [c["name"] for c in commands]
    lines.append("      " + " ".join(top_cmds))
    lines += [
        '    " -- "$cur))',
        "    return 0",
        "  fi",
        "",
        "  local cmd=${words[1]}",
        "  case $cmd in",
    ]
    for cmd in commands:
        if cmd["name"] in ("completion",):
            continue
        lines.append(f"    {cmd['name']})")
        for arg in cmd["args"]:
            if arg["flags"]:
                flag_str = " ".join(arg["flags"])
                if arg.get("type") == "flag":
                    lines.append(f"      COMPREPLY=($(compgen -W \"{flag_str}\" -- \"$cur\"))")
                else:
                    choices = arg.get("choices")
                    if choices:
                        choice_str = " ".join(str(c) for c in choices)
                        lines.append(f'      COMPREPLY=($(compgen -W "{flag_str} {choice_str}" -- "$cur"))')
                    else:
                        lines.append(f"      COMPREPLY=($(compgen -W \"{flag_str}\" -- \"$cur\"))")
        for sub in cmd["subcommands"]:
            sub_cmd = sub["name"]
            sub_flags = ""
            for a in sub["args"]:
                if a["flags"]:
                    sub_flags += " " + " ".join(a["flags"])
            if sub_flags:
                lines.append(f'      COMPREPLY=($(compgen -W "{sub_cmd}{sub_flags}" -- "$cur"))')
            else:
                lines.append(f"      COMPREPLY=($(compgen -W \"{sub_cmd}\" -- \"$cur\"))")
        if not cmd["args"] and not cmd["subcommands"]:
            lines.append("      COMPREPLY=()")
        lines.append("      ;;")
    lines += [
        "    *)",
        "      COMPREPLY=()",
        "      ;;",
        "  esac",
        "}",
        "complete -F _laura_completions laura",
        "",
    ]
    return "\n".join(lines)


def generate_zsh_script(commands: list[dict]) -> str:
    def _zsh_args(args_list: list[dict]) -> list[str]:
        out = []
        for a in args_list:
            if a["flags"]:
                main_flag = a["flags"][-1]
                desc = _escape(a.get("help", ""))
                if a.get("type") == "flag":
                    out.append(f"      \"{main_flag}[{desc}]\"")
                elif a.get("choices"):
                    choice_str = ":".join(str(c) for c in a["choices"])
                    out.append(f"      \"{main_flag}:{a['dest']}:({choice_str})\"")
                else:
                    out.append(f"      \"{main_flag}:{a['dest']}: \"")
        return out

    lines = [
        "#compdef laura",
        "",
        "_laura() {",
        "  local context state state_descr line",
        '  typeset -A opt_args',
        "",
        "  local -a all_commands",
    ]
    top_cmds = [c["name"] for c in commands]
    lines.append(f"  all_commands=({':'.join(top_cmds)})")
    lines += [
        "",
        "  _arguments -C \\",
        "    '1: :->command' \\",
        "    '*: :->args'",
        "",
        "  case $state in",
        "    command)",
        "      _describe 'laura command' all_commands",
        "      ;;",
        "    args)",
        "      case $words[1] in",
    ]
    for cmd in commands:
        if cmd["name"] in ("completion",):
            continue
        lines.append(f"        {cmd['name']})")
        cmd_args = _zsh_args(cmd["args"])
        if cmd["subcommands"]:
            sub_names = " ".join(s["name"] for s in cmd["subcommands"])
            lines.append(f"          _arguments \"1: :({sub_names})\"")
        elif cmd_args:
            lines.append("          _arguments \\")
            lines.extend(cmd_args)
        else:
            lines.append("          _arguments")
        lines.append("          ;;")
    lines += [
        "      esac",
        "      ;;",
        "  esac",
        "}",
        "",
        "_laura",
        "",
    ]
    return "\n".join(lines)


def generate_powershell_script(commands: list[dict]) -> str:
    lines = [
        "using namespace System.Management.Automation",
        "",
        "Register-ArgumentCompleter -Native -CommandName laura -ScriptBlock {",
        "  param($wordToComplete, $commandAst, $cursorPosition)",
        "",
        "  $commands = @{",
    ]
    for cmd in commands:
        if cmd["name"] in ("completion",):
            continue
        flag_list = []
        for a in cmd["args"]:
            if a["flags"]:
                flag_list.extend(a["flags"])
        flags_str = ", ".join(f"'{f}'" for f in flag_list)
        sub_str = ", ".join(f"'{s['name']}'" for s in cmd.get("subcommands", []))
        parts = [f"'{cmd['name']}'"]
        if flags_str:
            parts.append(f"@({flags_str})")
        else:
            parts.append("@()")
        if sub_str:
            parts.append(f"@({sub_str})")
        else:
            parts.append("@()")
        lines.append(f"    {chr(34)}{cmd['name']}{chr(34)} = @{{{': '.join(parts)}}}")
    lines += [
        "  }",
        "",
        "  $tokens = @($commandAst.CommandElements | Select-Object -Skip 1)",
        "  $currentCommand = if ($tokens.Count -gt 0) { $tokens[0].Value } else { $null }",
        "",
        "  if (-not $currentCommand -or -not $commands.ContainsKey($currentCommand)) {",
        "    $all = $commands.Keys | Where-Object { $_ -like \"$wordToComplete*\" }",
        "    return $all | ForEach-Object {",
        "      [CompletionResult]::new($_, $_, 'ParameterName', $commands[$_]['help'])",
        "    }",
        "  }",
        "",
        "  $cmdData = $commands[$currentCommand]",
        "  $flags = $cmdData['flags']",
        "  $subcommands = $cmdData['subcommands']",
        "",
        "  $currentToken = $tokens[-1].Value",
        "  $completions = @()",
        "",
        "  foreach ($f in $flags) {",
        "    if ($f -like \"$currentToken*\") {",
        "      $completions += [CompletionResult]::new($f, $f, 'ParameterName', $f)",
        "    }",
        "  }",
        "",
        "  foreach ($s in $subcommands) {",
        "    if ($s -like \"$currentToken*\") {",
        "      $completions += [CompletionResult]::new($s, $s, 'ParameterValue', $s)",
        "    }",
        "  }",
        "",
        "  return $completions",
        "}",
        "",
    ]
    return "\n".join(lines)


def build_parser(subparsers: argparse._SubParsersAction) -> None:
    completion_parser = subparsers.add_parser(
        "completion",
        help="Generate shell completion scripts",
    )
    completion_parser.add_argument(
        "shell",
        choices=["bash", "zsh", "powershell"],
        help="Target shell for completion script",
    )


def main() -> int:
    from shopee_agent.cli import build_parser as build_cli_parser

    parser = build_cli_parser()
    commands = _iter_subcommands(parser)

    if len(sys.argv) < 3 or sys.argv[1] != "completion":
        print("Usage: laura completion {bash,zsh,powershell}", file=sys.stderr)
        return 1

    shell = sys.argv[2]
    if shell == "bash":
        print(generate_bash_script(commands))
    elif shell == "zsh":
        print(generate_zsh_script(commands))
    elif shell == "powershell":
        print(generate_powershell_script(commands))
    else:
        print(f"Unknown shell: {shell}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
