// Ghidra headless post-script: dump decompiled C of every function to <outdir>/<program>.c
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import java.io.*;

public class ExportDecomp extends GhidraScript {
    @Override
    public void run() throws Exception {
        String outDir = getScriptArgs()[0];
        DecompInterface d = new DecompInterface();
        d.openProgram(currentProgram);
        File f = new File(outDir, currentProgram.getName() + ".c");
        try (PrintWriter w = new PrintWriter(new FileWriter(f))) {
            for (Function fn : currentProgram.getFunctionManager().getFunctions(true)) {
                if (fn.isExternal() || fn.isThunk()) continue;
                DecompileResults r = d.decompileFunction(fn, 60, monitor);
                w.println("// ==== " + fn.getName() + " @ " + fn.getEntryPoint());
                if (r != null && r.decompileCompleted())
                    w.println(r.getDecompiledFunction().getC());
                else
                    w.println("// decompile failed");
            }
        }
        println("wrote " + f);
    }
}
