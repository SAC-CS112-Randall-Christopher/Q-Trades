// Build-DesktopLauncher.ps1 replaces the project token when compiling locally.
// This executable opens the existing local application; it contains no trading code.
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Threading.Tasks;
using System.Windows.Forms;

[assembly: AssemblyTitle("Trading Research")]
[assembly: AssemblyDescription("Local paper trading dashboard launcher")]
[assembly: AssemblyVersion("1.0.0.0")]

internal static class TradingDashboardLauncher
{
    private const string ProjectRoot = @"{{PROJECT_ROOT}}";
    private const string RuntimeRoot = @"{{RUNTIME_ROOT}}";

    [STAThread]
    private static int Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        bool checkOnly = args.Length == 1 && args[0] == "--check";
        if (args.Length > 0 && !checkOnly) return 64;
        if (checkOnly) return RunScript(true);

        int result = 1;
        using (var window = new Form())
        {
            window.Text = "Trading Research";
            window.ClientSize = new Size(460, 132);
            window.FormBorderStyle = FormBorderStyle.FixedDialog;
            window.StartPosition = FormStartPosition.CenterScreen;
            window.MaximizeBox = false;
            window.MinimizeBox = false;
            window.ControlBox = false;
            window.Icon = SystemIcons.Application;
            window.Font = new Font("Segoe UI", 10);
            window.Controls.Add(new Label {
                Text = "Opening your local paper dashboard...",
                AutoSize = true, Location = new Point(22, 20)
            });
            window.Controls.Add(new Label {
                Text = "Starting the local service if needed. This can take up to 90 seconds.",
                MaximumSize = new Size(415, 45), AutoSize = true,
                Location = new Point(22, 51)
            });
            window.Controls.Add(new ProgressBar {
                Style = ProgressBarStyle.Marquee, MarqueeAnimationSpeed = 25,
                Location = new Point(22, 100), Size = new Size(415, 8)
            });
            window.Shown += async delegate {
                result = await Task.Run(() => RunScript(false));
                window.Close();
            };
            Application.Run(window);
        }
        return result;
    }

    private static int RunScript(bool checkOnly)
    {
        try
        {
            string script = Path.Combine(ProjectRoot, "scripts", "Open-TradingDashboard.ps1");
            if (!File.Exists(script))
                throw new InvalidOperationException("The application folder has moved or is missing:\n" + ProjectRoot);
            string powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
                @"WindowsPowerShell\v1.0\powershell.exe");
            var start = new ProcessStartInfo(powershell) {
                Arguments = "-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File \"" + script + "\"" +
                    (checkOnly ? " -CheckOnly" : "") +
                    (RuntimeRoot.Length == 0 ? "" : " -RuntimeRoot \"" + RuntimeRoot + "\""),
                WorkingDirectory = ProjectRoot,
                UseShellExecute = false, CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden,
                RedirectStandardOutput = true, RedirectStandardError = true
            };
            using (var child = Process.Start(start))
            {
                // Drain both streams asynchronously so errors cannot deadlock the launcher.
                Task<string> output = child.StandardOutput.ReadToEndAsync();
                Task<string> error = child.StandardError.ReadToEndAsync();
                child.WaitForExit();
                Task.WaitAll(output, error);
                if (checkOnly)
                {
                    string receipt = Path.Combine(RuntimeRoot.Length == 0 ? ProjectRoot : RuntimeRoot, "data", "desktop-launcher-check-" +
                        DateTime.UtcNow.ToString("yyyyMMddTHHmmssfffffffZ") + ".txt");
                    File.WriteAllText(receipt, output.Result + error.Result);
                }
                else if (child.ExitCode != 0)
                {
                    string detail = error.Result.Trim();
                    if (detail.Length == 0) detail = "The local dashboard could not be opened. Check data\\desktop-launcher.log in the application folder.";
                    if (detail.Length > 1600) detail = detail.Substring(0, 1600);
                    MessageBox.Show(detail, "Trading Research", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                }
                return child.ExitCode;
            }
        }
        catch (Exception exception)
        {
            if (!checkOnly)
                MessageBox.Show(exception.Message, "Trading Research", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return 1;
        }
    }
}
