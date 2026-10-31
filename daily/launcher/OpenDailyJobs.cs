// Open Daily Jobs.exe - starts the local jobs page server (daily\server.py) if it is
// not already running, then opens http://localhost:8765/ in the default browser.
// Build: csc /target:winexe /out:"..\..\Open Daily Jobs.exe" OpenDailyJobs.cs
using System;
using System.Diagnostics;
using System.IO;
using System.Net.Sockets;
using System.Threading;
using System.Windows.Forms;

static class OpenDailyJobs
{
    const int Port = 8765;
    const string Url = "http://localhost:8765/";

    static bool ServerUp()
    {
        try
        {
            using (var c = new TcpClient())
            {
                var ar = c.BeginConnect("127.0.0.1", Port, null, null);
                return ar.AsyncWaitHandle.WaitOne(300) && c.Connected;
            }
        }
        catch { return false; }
    }

    [STAThread]
    static void Main()
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string script = Path.Combine(root, "daily", "server.py");

        if (!ServerUp())
        {
            if (!File.Exists(script))
            {
                MessageBox.Show("Could not find " + script, "Open Daily Jobs");
                return;
            }
            bool started = false;
            foreach (string exe in new[] { "pythonw", "python" })
            {
                try
                {
                    Process.Start(new ProcessStartInfo(exe, "\"" + script + "\"")
                    {
                        WorkingDirectory = root,
                        UseShellExecute = false,
                        CreateNoWindow = true,
                    });
                    started = true;
                    break;
                }
                catch { }
            }
            if (!started)
            {
                MessageBox.Show("Python was not found, so the jobs page server could not start.", "Open Daily Jobs");
                return;
            }
            for (int i = 0; i < 25 && !ServerUp(); i++) Thread.Sleep(200);
        }

        Process.Start(new ProcessStartInfo(Url) { UseShellExecute = true });
    }
}
