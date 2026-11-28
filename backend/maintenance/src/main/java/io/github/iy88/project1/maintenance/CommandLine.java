package io.github.iy88.project1.maintenance;

/** Scans shared option syntax and delegates command-specific rules to {@link CommandOptions}. */
final class CommandLine {

    private CommandLine() {
    }

    static MaintenanceCli.Options parse(String[] args) {
        if (args.length < 3) {
            return null;
        }
        String command = args[0] + " " + args[1];
        var parsed = new ParsedOptions();
        for (int index = 2; index < args.length;) {
            String argument = args[index];
            if ("--prepare-reset".equals(argument) || "--reset".equals(argument)) {
                if (!parsed.markPrepareReset()) {
                    return null;
                }
                index++;
                continue;
            }
            String option;
            String value;
            int equals = argument.indexOf('=');
            if (argument.startsWith("--") && equals > 2) {
                option = argument.substring(0, equals);
                value = argument.substring(equals + 1);
                index++;
            } else {
                if (index + 1 >= args.length) {
                    return null;
                }
                option = argument;
                value = args[index + 1];
                index += 2;
            }
            if (value.isBlank() || value.startsWith("--") || !parsed.read(option, value)) {
                return null;
            }
        }
        if (parsed.envFile() == null) {
            return null;
        }
        return CommandOptions.resolve(command, parsed);
    }
}
