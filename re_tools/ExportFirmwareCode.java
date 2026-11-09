// Export static Ghidra analysis; firmware programs are never executed.
// Output may contain embedded credentials. Use a private directory outside Git.
// @category Firmware
import ghidra.app.util.headless.HeadlessScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import com.google.gson.Gson;
import java.io.BufferedWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.LinkedHashMap;
import java.util.Map;

public class ExportFirmwareCode extends HeadlessScript {
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1 || args.length > 2) throw new IllegalArgumentException("Supply private output directory and optional --per-program");
        Path out = Path.of(args[0]).toAbsolutePath().normalize();
        if (args.length == 2) {
            if (!args[1].equals("--per-program")) throw new IllegalArgumentException("Unknown option");
            String digest = currentProgram.getExecutableSHA256();
            if (digest == null || !digest.matches("[a-fA-F0-9]{64}")) throw new IllegalStateException("Missing SHA-256");
            out = out.resolve(digest.toLowerCase());
        }
        Files.createDirectories(out);
        out = out.toRealPath();
        for (Path p = out; p != null; p = p.getParent()) {
            if (Files.exists(p.resolve(".git"))) throw new IllegalArgumentException("Output must be outside Git");
        }
        Gson gson = new Gson();
        int recognized = 0, completed = 0, failed = 0;
        DecompInterface decompiler = new DecompInterface();
        if (!decompiler.openProgram(currentProgram)) throw new IllegalStateException(decompiler.getLastMessage());
        try (BufferedWriter code = Files.newBufferedWriter(out.resolve("pseudocode.c"), StandardCharsets.UTF_8);
             BufferedWriter asm = Files.newBufferedWriter(out.resolve("assembly.txt"), StandardCharsets.UTF_8);
             BufferedWriter index = Files.newBufferedWriter(out.resolve("functions.jsonl"), StandardCharsets.UTF_8)) {
            code.write("/* Generated pseudocode, not original or buildable source.\n" +
                       " * Function discovery and inferred types may be incomplete.\n" +
                       " * Embedded credentials may be present; keep this output private. */\n");
            asm.write("# Ghidra analysis-memory disassembly, not a runtime trace.\n");
            FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
            while (functions.hasNext()) {
                monitor.checkCancelled();
                Function function = functions.next();
                if (function.isExternal()) continue;
                recognized++;
                String address = function.getEntryPoint().toString();
                String name = function.getName().replace("*/", "* /");
                code.write("\n/* " + address + " " + name + " */\n");
                DecompileResults result = decompiler.decompileFunction(function, 15, monitor);
                boolean ok = result.decompileCompleted() && result.getDecompiledFunction() != null;
                if (ok) {
                    code.write(result.getDecompiledFunction().getC());
                    code.write("\n");
                    completed++;
                } else {
                    code.write("/* DECOMPILATION FAILED: " + result.getErrorMessage().replace("*/", "* /") + " */\n");
                    failed++;
                }
                Map<String,Object> row = new LinkedHashMap<>();
                row.put("address", address);
                row.put("name", function.getName());
                row.put("body", function.getBody().toString());
                row.put("decompiled", ok);
                row.put("error", ok ? null : result.getErrorMessage());
                index.write(gson.toJson(row)); index.newLine();
                asm.write("\n# " + address + " " + name + "\n");
                InstructionIterator instructions = currentProgram.getListing().getInstructions(function.getBody(), true);
                while (instructions.hasNext()) {
                    Instruction instruction = instructions.next();
                    asm.write(instruction.getAddress() + "  " + instruction.toString() + "\n");
                }
            }
        } finally {
            decompiler.dispose();
        }
        Map<String,Object> summary = new LinkedHashMap<>();
        summary.put("program", currentProgram.getName());
        summary.put("input_sha256", currentProgram.getExecutableSHA256());
        summary.put("language", currentProgram.getLanguageID().toString());
        summary.put("recognized_functions", recognized);
        summary.put("decompiled_functions", completed);
        summary.put("failed_functions", failed);
        summary.put("analysis_enabled_in_this_run", isHeadlessAnalysisEnabled());
        summary.put("analysis_timed_out", analysisTimeoutOccurred());
        summary.put("all_machine_code_proven_covered", false);
        Path temporary = out.resolve("summary.json.tmp");
        Files.writeString(temporary, gson.toJson(summary), StandardCharsets.UTF_8);
        Files.move(temporary, out.resolve("summary.json"), StandardCopyOption.ATOMIC_MOVE,
                   StandardCopyOption.REPLACE_EXISTING);
        println("Exported functions=" + recognized + " decompiled=" + completed + " failed=" + failed);
    }
}
