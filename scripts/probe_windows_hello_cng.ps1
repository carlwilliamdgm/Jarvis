<#
Probe Windows Hello through its application API (KeyCredentialManager), not
the lower-level Passport KSP. The uniquely named credential is always deleted.
Run from the signed-in Windows user's normal, interactive Windows PowerShell.
#>
[CmdletBinding()]
param([switch]$CheckOnly)

$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Ce probe nécessite Windows.' }

Add-Type -AssemblyName System.Runtime.WindowsRuntime

function Wait-WinRTOperation {
    param(
        [Parameter(Mandatory=$true)]$Operation,
        [Parameter(Mandatory=$true)][Type]$ResultType
    )

    $asTaskDefinition = [System.WindowsRuntimeSystemExtensions].GetMethods([Reflection.BindingFlags]'Public,Static') |
        Where-Object {
            $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and
            $_.GetGenericArguments().Count -eq 1 -and $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.IsGenericType -and
            $_.GetParameters()[0].ParameterType.GetGenericTypeDefinition().FullName -eq 'Windows.Foundation.IAsyncOperation`1'
        } | Select-Object -First 1
    if (-not $asTaskDefinition) { throw 'Conversion WinRT vers Task indisponible.' }

    $task = $asTaskDefinition.MakeGenericMethod($ResultType).Invoke($null, [object[]]@($Operation))
    return $task.GetAwaiter().GetResult()
}

function Wait-WinRTAction {
    param([Parameter(Mandatory=$true)]$Action)
    $actionType = [Windows.Foundation.IAsyncAction,Windows.Foundation,ContentType=WindowsRuntime]
    $asTask = [System.WindowsRuntimeSystemExtensions].GetMethods([Reflection.BindingFlags]'Public,Static') |
        Where-Object { $_.Name -eq 'AsTask' -and -not $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType -eq $actionType } |
        Select-Object -First 1
    if (-not $asTask) { throw 'Conversion WinRT IAsyncAction vers Task indisponible.' }
    $task = $asTask.Invoke($null, [object[]]@($Action))
    $task.GetAwaiter().GetResult()
}

function Invoke-KeyCredentialSignature {
    param(
        [Parameter(Mandatory=$true)]$Credential,
        [Parameter(Mandatory=$true)]$Data
    )
    $credentialType = [Windows.Security.Credentials.KeyCredential,Windows.Security.Credentials,ContentType=WindowsRuntime]
    $bufferType = [Windows.Storage.Streams.IBuffer,Windows.Storage,ContentType=WindowsRuntime]
    $signMethod = $credentialType.GetMethod('RequestSignAsync', [Type[]]@($bufferType))
    if (-not $signMethod) { throw 'Méthode KeyCredential.RequestSignAsync(IBuffer) introuvable.' }
    # PowerShell's direct binder cannot cast WinRT System.__ComObject to IBuffer.
    # Reflection passes the WinRT object through to the declared ABI interface.
    $operation = $signMethod.Invoke($Credential, [object[]]@($Data))
    $resultType = [Windows.Security.Credentials.KeyCredentialOperationResult,Windows.Security.Credentials,ContentType=WindowsRuntime]
    return Wait-WinRTOperation -Operation $operation -ResultType $resultType
}

$manager = [Windows.Security.Credentials.KeyCredentialManager,Windows.Security.Credentials,ContentType=WindowsRuntime]
$supported = Wait-WinRTOperation -Operation ($manager::IsSupportedAsync()) -ResultType ([bool])
if (-not $supported) {
    throw 'Windows indique que Hello / KeyCredentialManager n est pas pris en charge pour cet utilisateur ou cette session.'
}
Write-Host 'Windows Hello / KeyCredentialManager : pris en charge.'
if ($CheckOnly) { return }

$credentialId = 'GreatOS-Hello-Probe-' + [Guid]::NewGuid().ToString('N')
$creationRequested = $false
try {
    Write-Host 'Action 1/3 : Windows peut demander une confirmation Hello pour créer la clé temporaire.'
    $creationOption = [Windows.Security.Credentials.KeyCredentialCreationOption,Windows.Security.Credentials,ContentType=WindowsRuntime]::ReplaceExisting
    $creationRequested = $true
    $retrievalType = [Windows.Security.Credentials.KeyCredentialRetrievalResult,Windows.Security.Credentials,ContentType=WindowsRuntime]
    $creation = Wait-WinRTOperation -Operation ($manager::RequestCreateAsync($credentialId, $creationOption)) -ResultType $retrievalType
    if ($creation.Status.ToString() -ne 'Success') {
        throw "La création Hello a retourné le statut $($creation.Status)."
    }
    $credential = $creation.Credential

    $cryptographicBuffer = [Windows.Security.Cryptography.CryptographicBuffer,Windows.Security,ContentType=WindowsRuntime]
    $encoding = [Windows.Security.Cryptography.BinaryStringEncoding,Windows.Security,ContentType=WindowsRuntime]::Utf8
    $payload = $cryptographicBuffer::ConvertStringToBinary('GreatOS Hello credential probe', $encoding)

    Write-Host 'Action 2/3 : confirme la première signature si Windows le demande.'
    $signature1 = Invoke-KeyCredentialSignature -Credential $credential -Data $payload
    if ($signature1.Status.ToString() -ne 'Success' -or $signature1.Result.Length -eq 0) {
        throw "La première signature Hello a retourné le statut $($signature1.Status)."
    }

    Write-Host 'Action 3/3 : confirme la seconde signature si Windows le demande.'
    $signature2 = Invoke-KeyCredentialSignature -Credential $credential -Data $payload
    if ($signature2.Status.ToString() -ne 'Success' -or $signature2.Result.Length -eq 0) {
        throw "La seconde signature Hello a retourné le statut $($signature2.Status)."
    }

    Write-Host 'PASS : Windows Hello a cree la cle d application et produit deux signatures.' -ForegroundColor Green
} finally {
    if ($creationRequested) {
        try {
            $delete = $manager::DeleteAsync($credentialId)
            $null = Wait-WinRTAction -Action $delete
            Write-Host 'Clé temporaire supprimée.'
        } catch {
            Write-Warning "Suppression de la cle temporaire impossible pour l identifiant $credentialId : $($_.Exception.Message)"
        }
    }
}
