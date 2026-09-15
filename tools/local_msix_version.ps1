function Get-LocalMsixVersion {
    param(
        [Parameter(Mandatory)][version]$Highest,
        [datetime]$BuildDate = (Get-Date)
    )
    # Use the build machine's local calendar date. Never invent a future date
    # to work around a clock rollback or an exhausted daily sequence.
    $dateVersion = [version]::new($BuildDate.Year, $BuildDate.Month, $BuildDate.Day, 0)
    $highestDate = [version]::new($Highest.Major, $Highest.Minor, $Highest.Build, 0)
    if ($highestDate -gt $dateVersion) { throw 'LOCAL-MSIX-VERSION-DATE-BEHIND' }
    $sequence = 1
    if ($highestDate -eq $dateVersion) {
        if ($Highest.Revision -ge 65535) { throw 'LOCAL-MSIX-VERSION-EXHAUSTED' }
        $sequence = $Highest.Revision + 1
    }
    return [version]::new($BuildDate.Year, $BuildDate.Month, $BuildDate.Day, $sequence).ToString()
}
