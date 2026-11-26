RAGReel Tutorial (Houdini panel) - quick start
================================================

1. Extract the whole zip ("Extract All"), then run install.cmd in the extracted folder (double-click).
   Do not run it from inside the zip window. No administrator rights are needed.
   Enter the URL and the API key you were given (the key is not shown on screen).
   At the end, the installer prints a self-check ([OK] / [NG] / [attention] lines):
   where the files were written, which Houdini versions were registered, whether the URL and the key
   are filled in (their values are never shown), and the save folder.
   The same result is saved to  %LOCALAPPDATA%\RAGReelTutorial\install_report.txt
2. Start Houdini (restart it if it was already running).
   Open the panel from  Windows menu > Python Panel > RAGReel Tutorial,
   or from a pane tab menu (+) > New Pane Tab Type > RAGReel Tutorial (under Misc).
3. Open the Tutorial tab, type a topic, and press the generate button.
   The gear icon at the top right opens the screens you rarely need: History, Connection / account
   (URL, API key, save folder), and "open this panel in another window" (to look at two tabs side by side).

Generated tutorials and logs are saved to  Documents\RAGReelTutorial  unless you set another folder
(gear > Connection / account > save folder).

If the panel does not open or is not listed: run install.cmd again, restart Houdini, then open the
Python Shell in Houdini and run   import rag_chatbot   to see the real error.
All Houdini 22.0.x builds (for example 22.0.429 / 22.0.459 / 22.0.504) share one settings folder,
Documents\houdini22.0, so one registration covers them. Use  install.cmd -HoudiniVersion 22.0  to pick a version.

If the settings folder for your Houdini version (for example Documents\houdini22.0) does not exist yet,
the installer creates it, even when a folder for another version (houdini21.0) is already there.

To update: run install.cmd from the new zip again.
To remove: Settings > Apps > Installed apps > "RAGReel Tutorial (Houdini panel)" > Uninstall,
or run uninstall.cmd (same as install.cmd -Uninstall). Your settings file and generated tutorials are kept.

Install RAGReel (video engine) separately with RAGReel-Setup-<version>.exe if you want videos.
Full instructions (Japanese): install-other-pc.md (setup) and manual-houdini-tutorial.md (usage)
